import asyncio
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
from app.config import Settings
from app.models.telemetry import ServiceReference
from app.opensearch.query import OpenSearchQueryClient
from app.repositories.telemetry import TelemetryRepository

DEADLINE_SECONDS = min(int(os.environ.get("PHASE4_DEADLINE_SECONDS", "150")), 300)
ORDER_URL = os.environ.get("ORDER_SERVICE_URL", "http://order-service:8000")
ARTIFACT = Path(os.environ.get("PHASE4_ARTIFACT_PATH", "/artifacts/phase4-live.json"))
EXPECTED_EDGES = {
    ("order-service", "payment-service"),
    ("order-service", "inventory-service"),
}


def reference(name: str) -> ServiceReference:
    return ServiceReference(
        namespace="demo-shop",
        environment="development",
        name=name,
    )


def runtime_settings() -> Settings:
    return Settings(
        opensearch_url=os.environ.get("OPENSEARCH_URL", "https://opensearch:9200"),
        opensearch_username=os.environ["OPENSEARCH_ADMIN_USERNAME"],
        opensearch_password=os.environ["OPENSEARCH_ADMIN_PASSWORD"],
        opensearch_verify_tls=False,
    )


def valid_request_metrics(items) -> bool:
    by_name = {item.name: item for item in items}
    counter = by_name.get("demo.http.server.requests")
    duration = by_name.get("demo.http.server.duration")
    return bool(
        counter
        and counter.metric_type == "sum"
        and counter.unit == "{request}"
        and counter.temporality == "cumulative"
        and counter.monotonic is True
        and counter.value is not None
        and counter.value >= 1
        and duration
        and duration.metric_type == "histogram"
        and duration.unit == "ms"
        and duration.temporality == "cumulative"
        and duration.histogram
        and duration.histogram.count >= 1
        and len(duration.histogram.counts) == len(duration.histogram.bounds) + 1
    )


async def native_edge_sequences(client: OpenSearchQueryClient) -> dict[tuple[str, str], int]:
    payload = await client.search(
        "otel-v1-apm-service-map",
        {
            "size": 20,
            "seq_no_primary_term": True,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"kind": "SPAN_KIND_CLIENT"}},
                        {"term": {"serviceName": "order-service"}},
                        {
                            "terms": {
                                "destination.domain": [
                                    "payment-service",
                                    "inventory-service",
                                ]
                            }
                        },
                    ]
                }
            },
        },
    )
    sequences: dict[tuple[str, str], int] = {}
    for hit in payload.get("hits", {}).get("hits", []):
        source = hit.get("_source", {})
        edge = (
            source.get("serviceName"),
            source.get("destination", {}).get("domain"),
        )
        sequence = hit.get("_seq_no")
        if edge in EXPECTED_EDGES and isinstance(sequence, int):
            sequences[edge] = max(sequence, sequences.get(edge, -1))
    return sequences


async def run() -> dict[str, object]:
    settings = runtime_settings()
    query_client = OpenSearchQueryClient(settings)
    repository = TelemetryRepository(query_client, settings)
    started_at = datetime.now(UTC)
    started_monotonic = time.monotonic()
    request_id = f"phase4-{uuid4().hex}"
    first_seen: dict[str, float] = {}
    try:
        baseline_sequences = await native_edge_sequences(query_client)
        async with httpx.AsyncClient(timeout=5.0) as application:
            response = await application.post(
                f"{ORDER_URL}/orders",
                json={"product_id": "demo-product-1", "quantity": 1, "amount": 100.0},
                headers={"X-Request-ID": request_id},
            )
        if response.status_code != 200 or response.json().get("status") != "completed":
            raise RuntimeError("Real order workflow did not complete successfully")

        deadline = started_monotonic + DEADLINE_SECONDS
        trace_id = None
        trace_result = None
        log_results = {}
        metric_results = {}
        error_metric_results = {}
        dependency_result = None
        native_sequences: dict[tuple[str, str], int] = {}
        while time.monotonic() < deadline:
            now = datetime.now(UTC)
            window_start = started_at - timedelta(seconds=5)
            spans = await repository.search_spans(
                reference("order-service"),
                window_start,
                now,
                limit=100,
            )
            candidates = [
                span
                for span in spans.items
                if span.kind == "SERVER"
                and span.name == "POST /orders"
                and span.http_status_code == 200
            ]
            if candidates and trace_id is None:
                trace_id = candidates[-1].trace_id
                first_seen["spans"] = time.monotonic() - started_monotonic
            if trace_id:
                trace_result = await repository.get_trace(
                    trace_id,
                    start_time=window_start,
                    end_time=now,
                )
                for service_name in ("order-service", "payment-service", "inventory-service"):
                    logs = await repository.search_logs(
                        reference(service_name),
                        window_start,
                        now,
                        trace_id=trace_id,
                        limit=20,
                    )
                    if logs.items:
                        log_results[service_name] = logs
                if len(log_results) == 3 and "logs" not in first_seen:
                    first_seen["logs"] = time.monotonic() - started_monotonic
            for service_name in ("order-service", "payment-service", "inventory-service"):
                metrics = await repository.get_native_metrics(
                    reference(service_name),
                    window_start,
                    now,
                    metric_names=[
                        "demo.http.server.requests",
                        "demo.http.server.duration",
                    ],
                    limit=20,
                )
                if valid_request_metrics(metrics.items):
                    metric_results[service_name] = metrics
                errors = await repository.get_native_metrics(
                    reference(service_name),
                    now - timedelta(hours=24),
                    now,
                    metric_names=["demo.http.server.errors"],
                    limit=20,
                )
                valid_errors = [
                    item
                    for item in errors.items
                    if item.metric_type == "sum"
                    and item.unit == "{request}"
                    and item.temporality == "cumulative"
                    and item.monotonic is True
                    and item.value is not None
                    and item.value >= 1
                ]
                if valid_errors:
                    error_metric_results[service_name] = errors
            if len(metric_results) == 3 and "metrics" not in first_seen:
                first_seen["metrics"] = time.monotonic() - started_monotonic
            dependency_result = await repository.get_service_dependencies(
                None,
                window_start,
                now,
                limit=20,
            )
            normalized_edges = {
                (edge.source_service.name, edge.target_service.name)
                for edge in dependency_result.items
            }
            if EXPECTED_EDGES <= normalized_edges and "dependencies" not in first_seen:
                first_seen["dependencies"] = time.monotonic() - started_monotonic
            native_sequences = await native_edge_sequences(query_client)
            if (
                EXPECTED_EDGES <= set(native_sequences)
                and "native_service_map" not in first_seen
            ):
                first_seen["native_service_map"] = time.monotonic() - started_monotonic

            connected = (
                trace_result is not None
                and trace_result.items
                and len(trace_result.items[0].spans) >= 5
            )
            if (
                connected
                and len(log_results) == 3
                and len(metric_results) == 3
                and len(error_metric_results) == 3
                and EXPECTED_EDGES <= normalized_edges
                and "native_service_map" in first_seen
            ):
                break
            await asyncio.sleep(1)
        else:
            raise RuntimeError("Phase 4 telemetry was not fully queryable before the deadline")

        assert trace_id is not None
        assert trace_result is not None and trace_result.items
        assert dependency_result is not None
        normalized_edges = {
            (edge.source_service.name, edge.target_service.name)
            for edge in dependency_result.items
        }
        if ("payment-service", "inventory-service") in normalized_edges:
            raise RuntimeError("Unexpected Payment to Inventory business dependency")
        trace = trace_result.items[0]
        result: dict[str, object] = {
            "request_id": request_id,
            "trace_id": trace_id,
            "request_status": response.status_code,
            "ingestion_delay_seconds": {
                key: round(value, 3) for key, value in sorted(first_seen.items())
            },
            "trace": {
                "span_count": len(trace.spans),
                "services": sorted(item.name for item in trace.services),
                "root_present": trace.root_present,
                "missing_parent_count": trace.missing_parent_count,
                "partial": trace_result.metadata.partial,
            },
            "logs": {
                name: {
                    "count": len(value.items),
                    "partial": value.metadata.partial,
                }
                for name, value in sorted(log_results.items())
            },
            "metrics": {
                name: {
                    item.name: {
                        "type": item.metric_type,
                        "unit": item.unit,
                        "temporality": item.temporality,
                        "monotonic": item.monotonic,
                        "value": item.value,
                        "histogram_count": (
                            item.histogram.count if item.histogram is not None else None
                        ),
                        "histogram_bucket_count": (
                            len(item.histogram.counts)
                            if item.histogram is not None
                            else None
                        ),
                    }
                    for item in value.items
                    if item.name
                    in {"demo.http.server.requests", "demo.http.server.duration"}
                }
                for name, value in sorted(metric_results.items())
            },
            "error_counters": {
                name: {
                    "unit": value.items[-1].unit,
                    "temporality": value.items[-1].temporality,
                    "monotonic": value.items[-1].monotonic,
                    "value": value.items[-1].value,
                }
                for name, value in sorted(error_metric_results.items())
            },
            "dependencies": [list(edge) for edge in sorted(normalized_edges)],
            "native_service_map_sequences": {
                f"{source}->{target}": native_sequences[(source, target)]
                for source, target in sorted(EXPECTED_EDGES)
            },
            "native_service_map_attributable_to_run": all(
                native_sequences[edge] > baseline_sequences.get(edge, -1)
                for edge in EXPECTED_EDGES
            ),
        }
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        await query_client.close()


def main() -> int:
    result = asyncio.run(run())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
