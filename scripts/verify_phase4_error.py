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

DEADLINE_SECONDS = min(int(os.environ.get("PHASE4_DEADLINE_SECONDS", "60")), 120)
ARTIFACT = Path(
    os.environ.get("PHASE4_ERROR_ARTIFACT_PATH", "/artifacts/phase4-error.json")
)


def reference(name: str) -> ServiceReference:
    return ServiceReference(
        namespace="demo-shop",
        environment="development",
        name=name,
    )


async def run() -> dict[str, object]:
    settings = Settings(
        opensearch_url=os.environ.get("OPENSEARCH_URL", "https://opensearch:9200"),
        opensearch_username=os.environ["OPENSEARCH_ADMIN_USERNAME"],
        opensearch_password=os.environ["OPENSEARCH_ADMIN_PASSWORD"],
        opensearch_verify_tls=False,
    )
    query_client = OpenSearchQueryClient(settings)
    repository = TelemetryRepository(query_client, settings)
    started_at = datetime.now(UTC)
    try:
        async with httpx.AsyncClient(timeout=5.0) as application:
            armed = await application.post(
                "http://payment-service:8000/__faults",
                json={"mode": "errors", "duration_seconds": 20.0, "latency_ms": 250},
            )
            if armed.status_code != 200:
                raise RuntimeError("Controlled payment fault endpoint is unavailable")
            response = await application.post(
                "http://order-service:8000/orders",
                json={"product_id": "demo-product-1", "quantity": 1, "amount": 100.0},
                headers={"X-Request-ID": f"phase4-error-{uuid4().hex}"},
            )
        if response.status_code != 502:
            raise RuntimeError("Controlled payment error did not produce the expected 502")

        deadline = time.monotonic() + DEADLINE_SECONDS
        while time.monotonic() < deadline:
            now = datetime.now(UTC)
            start = started_at - timedelta(seconds=2)
            spans = await repository.search_spans(
                reference("order-service"),
                start,
                now,
                status="error",
                limit=50,
            )
            roots = [
                span
                for span in spans.items
                if span.kind == "SERVER"
                and span.name == "POST /orders"
                and span.http_status_code == 502
            ]
            if not roots:
                await asyncio.sleep(1)
                continue
            trace_id = roots[-1].trace_id
            trace_result = await repository.get_trace(
                trace_id,
                start_time=start,
                end_time=now,
            )
            logs = {}
            for service_name in ("order-service", "payment-service"):
                result = await repository.search_logs(
                    reference(service_name),
                    start,
                    now,
                    severity="ERROR",
                    trace_id=trace_id,
                    limit=10,
                )
                if result.items:
                    logs[service_name] = result
            if trace_result.items and len(logs) == 2:
                trace = trace_result.items[0]
                statuses = {
                    (span.service.name, span.kind, span.http_status_code, span.status)
                    for span in trace.spans
                    if span.http_status_code is not None
                }
                if (
                    ("order-service", "SERVER", 502, "ERROR") not in statuses
                    or ("payment-service", "SERVER", 500, "ERROR") not in statuses
                ):
                    raise RuntimeError("Normalized error trace has unexpected status semantics")
                result: dict[str, object] = {
                    "trace_id": trace_id,
                    "request_status": response.status_code,
                    "span_count": len(trace.spans),
                    "services": sorted(item.name for item in trace.services),
                    "error_logs": {
                        name: [item.event for item in value.items]
                        for name, value in sorted(logs.items())
                    },
                    "partial": trace_result.metadata.partial
                    or any(value.metadata.partial for value in logs.values()),
                }
                ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
                ARTIFACT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                return result
            await asyncio.sleep(1)
        raise RuntimeError("Phase 4 error telemetry was not queryable before the deadline")
    finally:
        await query_client.close()


def main() -> int:
    result = asyncio.run(run())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
