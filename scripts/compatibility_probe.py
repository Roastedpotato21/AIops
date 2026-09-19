import json
import logging
import os
import time
import uuid
from pathlib import Path

import httpx
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.metrics import Observation
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind

OTLP_ENDPOINT = os.environ.get("OTLP_ENDPOINT", "otel-collector:4317")
OPENSEARCH_URL = os.environ.get("OPENSEARCH_URL", "https://opensearch:9200")
AUTH = (os.environ["OPENSEARCH_ADMIN_USERNAME"], os.environ["OPENSEARCH_ADMIN_PASSWORD"])
DEADLINE = int(os.environ.get("PROBE_DEADLINE_SECONDS", "180"))
ARTIFACT_DIR = Path(os.environ.get("PROBE_ARTIFACT_DIR", "/tmp/probe-artifacts"))
SERVICES = ("order-service", "payment-service", "inventory-service")
ROUTES = {
    "order-service": "/orders",
    "payment-service": "/payments",
    "inventory-service": "/inventory/reserve",
}


def resource(service: str, run_id: str) -> Resource:
    return Resource.create(
        {
            "service.namespace": "compatibility-probe",
            "service.name": service,
            "service.instance.id": f"{service}-{run_id}",
            "deployment.environment.name": "development",
            "aiops.probe.run_id": run_id,
        }
    )


def span_name(service: str, run_id: str) -> str:
    return f"compatibility-probe {run_id} POST {ROUTES[service]}"


def emit(run_id: str) -> None:
    providers: list[TracerProvider] = []
    tracers = []
    for service in SERVICES:
        provider = TracerProvider(resource=resource(service, run_id))
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP_ENDPOINT, insecure=True))
        )
        providers.append(provider)
        tracers.append(provider.get_tracer("aiops.compatibility-probe", "1.0.0"))
    span_attributes = {
        "aiops.probe.run_id": run_id,
        "http.response.status_code": 200,
    }
    with (
        tracers[0].start_as_current_span(
            span_name(SERVICES[0], run_id),
            kind=SpanKind.SERVER,
            attributes={**span_attributes, "http.route": ROUTES[SERVICES[0]]},
        ),
        tracers[1].start_as_current_span(
            span_name(SERVICES[1], run_id),
            kind=SpanKind.SERVER,
            attributes={**span_attributes, "http.route": ROUTES[SERVICES[1]]},
        ),
        tracers[2].start_as_current_span(
            span_name(SERVICES[2], run_id),
            kind=SpanKind.SERVER,
            attributes={**span_attributes, "http.route": ROUTES[SERVICES[2]]},
        ),
    ):
        pass
    for provider in providers:
        if not provider.force_flush(10_000):
            raise RuntimeError("Trace export did not flush")
        provider.shutdown()

    for service in SERVICES:
        provider = LoggerProvider(resource=resource(service, run_id))
        provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=OTLP_ENDPOINT, insecure=True))
        )
        logger = logging.getLogger(f"probe.{service}.{run_id}")
        logger.handlers = [LoggingHandler(logger_provider=provider)]
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.info("compatibility probe event", extra={"aiops.probe.run_id": run_id})
        if not provider.force_flush(10_000):
            raise RuntimeError("Log export did not flush")
        provider.shutdown()

    for service in SERVICES:
        reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=OTLP_ENDPOINT, insecure=True), export_interval_millis=1_000
        )
        provider = MeterProvider(resource=resource(service, run_id), metric_readers=[reader])
        meter = provider.get_meter("aiops.compatibility-probe", "1.0.0")
        counter = meter.create_counter("aiops.probe.requests", unit="{request}")
        histogram = meter.create_histogram("aiops.probe.latency", unit="ms")
        meter.create_observable_gauge(
            "aiops.telemetry.heartbeat",
            callbacks=[lambda _options, value=run_id: [Observation(1, {"aiops.probe.run_id": value})]],
            unit="1",
        )
        attrs = {"aiops.probe.run_id": run_id, "service.name": service}
        counter.add(1, attrs)
        histogram.record(12.5, attrs)
        if not provider.force_flush(10_000):
            raise RuntimeError("Metric export did not flush")
        provider.shutdown()


def sources(hits: list[dict]) -> list[dict]:
    return [hit["_source"] for hit in hits]


def service_name(source: dict) -> str:
    return source.get(
        "serviceName", source.get("resource", {}).get("attributes", {}).get("service.name", "")
    )


def search_run(client: httpx.Client, pattern: str, run_id: str, size: int = 200) -> list[dict]:
    response = client.get(
        f"/{pattern}/_search",
        params={"size": size, "ignore_unavailable": "true", "q": run_id},
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()
    return response.json().get("hits", {}).get("hits", [])


def search_service_map(client: httpx.Client, run_id: str, size: int = 20) -> list[dict]:
    response = client.post(
        "/otel-v1-apm-service-map*/_search",
        params={"ignore_unavailable": "true"},
        json={
            "size": size,
            "query": {"wildcard": {"traceGroupName": {"value": f"*{run_id}*"}}},
        },
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()
    return response.json().get("hits", {}).get("hits", [])


def validate_logs(logs: list[dict], run_id: str) -> bool:
    documents = sources(logs)
    return (
        {service_name(document) for document in documents} == set(SERVICES)
        and all(document.get("body") == "compatibility probe event" for document in documents)
        and all(document.get("severityText") == "INFO" for document in documents)
        and all(
            document.get("attributes", {}).get("aiops.probe.run_id") == run_id
            for document in documents
        )
    )


def metric_matches(document: dict, service: str, name: str, kind: str, unit: str) -> bool:
    if service_name(document) != service:
        return False
    if (document.get("name"), document.get("kind"), document.get("unit")) != (name, kind, unit):
        return False
    if name == "aiops.probe.requests":
        return document.get("value") == 1.0 and document.get("isMonotonic") is True
    if name == "aiops.probe.latency":
        return (
            document.get("count") == 1
            and document.get("sum") == 12.5
            and document.get("min") == 12.5
            and document.get("max") == 12.5
            and any(
                bucket.get("min") == 10.0
                and bucket.get("max") == 25.0
                and bucket.get("count") == 1
                for bucket in document.get("buckets", [])
            )
        )
    return document.get("value") == 1.0


def validate_metric(metrics: list[dict], name: str, kind: str, unit: str) -> bool:
    documents = sources(metrics)
    return all(
        any(metric_matches(document, service, name, kind, unit) for document in documents)
        for service in SERVICES
    )


def validate_spans(spans: list[dict], run_id: str) -> tuple[bool, dict]:
    documents = sources(spans)
    by_service = {service_name(document): document for document in documents}
    if len(documents) != 3 or set(by_service) != set(SERVICES):
        return False, {}
    order, payment, inventory = (by_service[service] for service in SERVICES)
    trace_ids = {document.get("traceId") for document in documents}
    valid = (
        len(trace_ids) == 1
        and None not in trace_ids
        and order.get("parentSpanId") == ""
        and payment.get("parentSpanId") == order.get("spanId")
        and inventory.get("parentSpanId") == payment.get("spanId")
        and all(
            document.get("name") == span_name(service, run_id)
            and document.get("kind") == "SPAN_KIND_SERVER"
            and document.get("attributes", {}).get("http.route") == ROUTES[service]
            and document.get("attributes", {}).get("http.response.status_code") == 200
            for service, document in by_service.items()
        )
    )
    evidence = {
        "trace_id": order.get("traceId"),
        "spans": [
            {
                "service": service,
                "name": document.get("name"),
                "span_id": document.get("spanId"),
                "parent_span_id": document.get("parentSpanId"),
            }
            for service, document in by_service.items()
        ],
    }
    return valid, evidence


def validate_service_map(maps: list[dict]) -> tuple[bool, list[dict[str, str]]]:
    edges = sorted(
        {
            (document.get("serviceName", ""), document.get("destination", {}).get("domain", ""))
            for document in sources(maps)
            if document.get("destination")
        }
    )
    expected = {("order-service", "payment-service"), ("payment-service", "inventory-service")}
    evidence = [{"source": source, "destination": destination} for source, destination in edges]
    return expected.issubset(set(edges)), evidence


def metric_evidence(metrics: list[dict]) -> list[dict]:
    examples = []
    for service in SERVICES:
        for name in ("aiops.probe.requests", "aiops.probe.latency", "aiops.telemetry.heartbeat"):
            document = next(
                item
                for item in sources(metrics)
                if service_name(item) == service and item.get("name") == name
            )
            examples.append(
                {
                    "service": service,
                    "name": name,
                    "kind": document.get("kind"),
                    "unit": document.get("unit"),
                    "value": document.get("value"),
                    "count": document.get("count"),
                    "sum": document.get("sum"),
                }
            )
    return examples


def main() -> None:
    if not 1 <= DEADLINE <= 300:
        raise SystemExit("PROBE_DEADLINE_SECONDS must be between 1 and 300")
    run_id = uuid.uuid4().hex
    started = time.monotonic()
    print(f"Compatibility probe run_id={run_id}")
    emit(run_id)
    deadline = started + DEADLINE
    result: dict[str, object] = {"run_id": run_id, "checks": {}}
    with httpx.Client(base_url=OPENSEARCH_URL, auth=AUTH, verify=False, timeout=10.0) as client:
        while time.monotonic() < deadline:
            logs = search_run(client, "aiops-logs-*", run_id)
            metrics = search_run(client, "aiops-metrics-raw-*", run_id)
            spans = search_run(client, "otel-v1-apm-span*", run_id)
            maps = search_service_map(client, run_id)
            spans_valid, trace_evidence = validate_spans(spans, run_id)
            maps_valid, edges = validate_service_map(maps)
            checks = {
                "logs": validate_logs(logs, run_id),
                "counter": validate_metric(metrics, "aiops.probe.requests", "SUM", "{request}"),
                "histogram": validate_metric(metrics, "aiops.probe.latency", "HISTOGRAM", "ms"),
                "gauge": validate_metric(metrics, "aiops.telemetry.heartbeat", "GAUGE", "1"),
                "spans": spans_valid,
                "service_map": maps_valid,
            }
            result = {
                "run_id": run_id,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "checks": checks,
                "counts": {
                    "logs": len(logs),
                    "metrics": len(metrics),
                    "spans": len(spans),
                    "service_maps": len(maps),
                },
            }
            if all(checks.values()):
                result["evidence"] = {
                    "logs": [
                        {
                            "service": service_name(document),
                            "body": document.get("body"),
                            "severity": document.get("severityText"),
                            "time": document.get("time"),
                        }
                        for document in sources(logs)
                    ],
                    "metrics": metric_evidence(metrics),
                    "trace": trace_evidence,
                    "service_edges": edges,
                }
                ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
                (ARTIFACT_DIR / "latest-probe.json").write_text(
                    json.dumps(result, indent=2) + "\n", encoding="utf-8"
                )
                print(json.dumps(result, indent=2))
                return
            time.sleep(2)
    print(json.dumps(result, indent=2))
    raise SystemExit("Compatibility probe deadline exceeded")


if __name__ == "__main__":
    main()
