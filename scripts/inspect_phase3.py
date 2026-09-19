import json
import os
import time
from typing import Any

import httpx

OPENSEARCH_URL = os.environ.get("OPENSEARCH_URL", "https://opensearch:9200")
AUTH = (
    os.environ["OPENSEARCH_ADMIN_USERNAME"],
    os.environ["OPENSEARCH_ADMIN_PASSWORD"],
)
DEADLINE_SECONDS = min(int(os.environ.get("PHASE3_INSPECTION_DEADLINE_SECONDS", "60")), 120)
TRACE_ID = os.environ.get("PHASE3_TRACE_ID")
NAMESPACE = os.environ.get("OTEL_SERVICE_NAMESPACE", "demo-shop")
SERVICES = {"order-service", "payment-service", "inventory-service"}


def search(client: httpx.Client, pattern: str, query: str, size: int = 200) -> list[dict]:
    response = client.get(
        f"/{pattern}/_search",
        params={
            "ignore_unavailable": "true",
            "q": query,
            "size": size,
            "sort": "_doc",
        },
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()
    return response.json().get("hits", {}).get("hits", [])


def sources(hits: list[dict]) -> list[dict]:
    return [hit["_source"] for hit in hits]


def resource_service(document: dict) -> str:
    return (
        document.get("resource", {})
        .get("attributes", {})
        .get("service.name", "")
    )


def is_application_document(document: dict) -> bool:
    attributes = document.get("resource", {}).get("attributes", {})
    return attributes.get("service.namespace") == NAMESPACE


def find_trace_id(client: httpx.Client) -> str | None:
    if TRACE_ID:
        return TRACE_ID
    candidates = sources(
        search(
            client,
            "otel-v1-apm-span*",
            "serviceName:order-service AND name:\"POST /orders\"",
        )
    )
    candidates = [
        item
        for item in candidates
        if is_application_document(item)
        and item.get("kind") == "SPAN_KIND_SERVER"
        and item.get("name") == "POST /orders"
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.get("startTime", "")).get("traceId")


def main_spans(documents: list[dict]) -> list[dict]:
    return [
        item
        for item in documents
        if item.get("kind") in {"SPAN_KIND_SERVER", "SPAN_KIND_CLIENT"}
    ]


def validate_trace(documents: list[dict]) -> tuple[bool, list[dict[str, Any]]]:
    spans = main_spans(documents)
    servers = {
        item.get("serviceName"): item
        for item in spans
        if item.get("kind") == "SPAN_KIND_SERVER"
    }
    order_server = servers.get("order-service")
    clients = [
        item
        for item in spans
        if item.get("serviceName") == "order-service"
        and item.get("kind") == "SPAN_KIND_CLIENT"
    ]

    def client_for(host: str) -> dict | None:
        return next(
            (
                item
                for item in clients
                if host in str(item.get("attributes", {}).get("http.url", ""))
            ),
            None,
        )

    payment_client = client_for("payment-service")
    inventory_client = client_for("inventory-service")
    valid = bool(
        set(servers) == SERVICES
        and order_server
        and payment_client
        and inventory_client
        and payment_client.get("parentSpanId") == order_server.get("spanId")
        and inventory_client.get("parentSpanId") == order_server.get("spanId")
        and servers["payment-service"].get("parentSpanId")
        == payment_client.get("spanId")
        and servers["inventory-service"].get("parentSpanId")
        == inventory_client.get("spanId")
    )
    evidence = [
        {
            "service": item.get("serviceName"),
            "name": item.get("name"),
            "kind": item.get("kind"),
            "span_id": item.get("spanId"),
            "parent_span_id": item.get("parentSpanId"),
            "status": item.get("attributes", {}).get("http.status_code"),
            "duration_ms": round(item.get("durationInNanos", 0) / 1_000_000, 3),
        }
        for item in spans
    ]
    return valid, evidence


def validate_logs(documents: list[dict], trace_id: str) -> tuple[bool, list[dict]]:
    application = [item for item in documents if is_application_document(item)]
    evidence = [
        {
            "service": resource_service(item),
            "body": item.get("body"),
            "severity": item.get("severityText"),
            "trace_id": item.get("traceId"),
            "span_id": item.get("spanId"),
        }
        for item in application
    ]
    return (
        {item["service"] for item in evidence} == SERVICES
        and all(item["trace_id"] == trace_id and item["span_id"] for item in evidence),
        evidence,
    )


def validate_metrics(documents: list[dict]) -> tuple[bool, list[dict]]:
    expected = {"demo.http.server.requests", "demo.http.server.duration"}
    application = [item for item in documents if is_application_document(item)]
    keys = {(resource_service(item), item.get("name")) for item in application}
    valid = all((service, name) in keys for service in SERVICES for name in expected)
    evidence = []
    seen = set()
    for item in application:
        key = (resource_service(item), item.get("name"))
        if key in seen or item.get("name") not in expected | {"demo.http.server.errors"}:
            continue
        seen.add(key)
        evidence.append(
            {
                "service": key[0],
                "name": key[1],
                "kind": item.get("kind"),
                "unit": item.get("unit"),
            }
        )
    return valid, sorted(evidence, key=lambda item: (item["service"], item["name"]))


def run() -> int:
    deadline = time.monotonic() + DEADLINE_SECONDS
    with httpx.Client(
        base_url=OPENSEARCH_URL,
        auth=AUTH,
        verify=False,
        timeout=10.0,
    ) as client:
        trace_id = find_trace_id(client)
        if not trace_id:
            raise RuntimeError("No real application order trace was found")
        while time.monotonic() < deadline:
            span_documents = sources(
                search(client, "otel-v1-apm-span*", f"traceId:{trace_id}", 100)
            )
            log_documents = sources(
                search(client, "aiops-logs-*", f"traceId:{trace_id}", 50)
            )
            metric_documents = sources(
                search(client, "aiops-metrics-raw-*", "name:demo.http.server.*")
            )
            trace_ok, span_evidence = validate_trace(span_documents)
            logs_ok, log_evidence = validate_logs(log_documents, trace_id)
            metrics_ok, metric_evidence = validate_metrics(metric_documents)
            if trace_ok and logs_ok and metrics_ok:
                print(
                    json.dumps(
                        {
                            "trace_id": trace_id,
                            "checks": {
                                "connected_trace": trace_ok,
                                "correlated_logs": logs_ok,
                                "native_metrics": metrics_ok,
                            },
                            "spans": span_evidence,
                            "logs": log_evidence,
                            "metrics": metric_evidence,
                        },
                        indent=2,
                    )
                )
                return 0
            time.sleep(1)
    raise RuntimeError("Phase 3 telemetry did not become queryable before the deadline")


if __name__ == "__main__":
    raise SystemExit(run())
