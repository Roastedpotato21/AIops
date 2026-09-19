import io
import json
from collections.abc import Mapping
from urllib.parse import urlparse

import httpx
import pytest
from aiops_telemetry import TelemetrySettings, configure_telemetry
from aiops_telemetry.runtime import (
    DURATION_METRIC,
    ERRORS_METRIC,
    REQUESTS_METRIC,
    TelemetryRuntime,
    build_resource,
)
from inventory_service.config import InventorySettings
from inventory_service.main import create_app as create_inventory_app
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from order_service.config import OrderSettings
from order_service.main import create_app as create_order_app
from payment_service.config import PaymentSettings
from payment_service.main import create_app as create_payment_app

ORDER = {"product_id": "demo-product-1", "quantity": 1, "amount": 100.0}


class RoutingTransport(httpx.AsyncBaseTransport):
    def __init__(self, apps: Mapping[str, object]) -> None:
        self._transports = {
            host: httpx.ASGITransport(app=app)  # type: ignore[arg-type]
            for host, app in apps.items()
        }

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._transports[request.url.host].handle_async_request(request)

    async def aclose(self) -> None:
        for transport in self._transports.values():
            await transport.aclose()


def telemetry_settings(service: str, *, enabled: bool = True) -> TelemetrySettings:
    return TelemetrySettings(
        telemetry_enabled=enabled,
        otel_service_name=service,
        otel_service_namespace="demo-shop",
        service_version="0.3.0-test",
        service_instance_id=f"{service}-test",
        deployment_environment="test",
    )


def runtime(
    service: str,
    spans: InMemorySpanExporter,
    logs: InMemoryLogRecordExporter,
    metrics: InMemoryMetricReader,
    stream: io.StringIO | None = None,
) -> TelemetryRuntime:
    return configure_telemetry(
        telemetry_settings(service),
        span_exporter=spans,
        log_exporter=logs,
        metric_reader=metrics,
        log_stream=stream,
    )


def metric_values(reader: InMemoryMetricReader) -> dict[str, tuple[int, float]]:
    values: dict[str, tuple[int, float]] = {}
    data = reader.get_metrics_data()
    assert data is not None
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                points = metric.data.data_points
                if points and hasattr(points[0], "count"):
                    values[metric.name] = (
                        sum(point.count for point in points),
                        sum(point.sum for point in points),
                    )
                else:
                    values[metric.name] = (sum(point.value for point in points), 0.0)
    return values


def peer_host(span: object) -> str | None:
    attributes = span.attributes  # type: ignore[attr-defined]
    direct = attributes.get("server.address") or attributes.get("net.peer.name")
    if direct:
        return str(direct)
    url = attributes.get("url.full") or attributes.get("http.url")
    return urlparse(str(url)).hostname if url else None


def test_service_resource_identity() -> None:
    resource = build_resource(telemetry_settings("order-service"))
    assert resource.attributes["service.name"] == "order-service"
    assert resource.attributes["service.namespace"] == "demo-shop"
    assert resource.attributes["service.version"] == "0.3.0-test"
    assert resource.attributes["service.instance.id"] == "order-service-test"
    assert resource.attributes["deployment.environment.name"] == "test"


@pytest.mark.asyncio
async def test_connected_trace_propagates_to_payment_and_inventory() -> None:
    spans = InMemorySpanExporter()
    logs = InMemoryLogRecordExporter()
    order_runtime = runtime("order-service", spans, logs, InMemoryMetricReader())
    payment_runtime = runtime("payment-service", spans, logs, InMemoryMetricReader())
    inventory_runtime = runtime("inventory-service", spans, logs, InMemoryMetricReader())
    payment = create_payment_app(
        PaymentSettings(app_environment="test"), telemetry_runtime=payment_runtime
    )
    inventory = create_inventory_app(
        InventorySettings(app_environment="test"), telemetry_runtime=inventory_runtime
    )
    downstream = httpx.AsyncClient(
        transport=RoutingTransport(
            {"payment-service": payment, "inventory-service": inventory}
        )
    )
    order = create_order_app(
        OrderSettings(), downstream, telemetry_runtime=order_runtime
    )
    async with downstream, httpx.AsyncClient(
        transport=httpx.ASGITransport(app=order), base_url="http://order-service"
    ) as client:
        response = await client.post("/orders", json=ORDER)
    assert response.status_code == 200

    finished = spans.get_finished_spans()
    entries = {
        span.resource.attributes["service.name"]: span
        for span in finished
        if span.name in {"POST /orders", "POST /payments", "POST /reserve"}
    }
    clients = [span for span in finished if span.kind is SpanKind.CLIENT]
    span_summary = [
        (
            span.name,
            span.kind.name,
            span.resource.attributes.get("service.name"),
            f"{span.context.trace_id:032x}",
        )
        for span in finished
    ]
    # ASGITransport keeps the active context in-process, so downstream app entry
    # spans are INTERNAL here; the live container test verifies real SERVER spans.
    assert set(entries) == {
        "order-service",
        "payment-service",
        "inventory-service",
    }, span_summary
    assert len({span.context.trace_id for span in entries.values()}) == 1
    order_server = entries["order-service"]
    payment_client = next(
        span for span in clients if peer_host(span) == "payment-service"
    )
    inventory_client = next(
        span for span in clients if peer_host(span) == "inventory-service"
    )
    assert payment_client.parent.span_id == order_server.context.span_id
    assert entries["payment-service"].parent.span_id == payment_client.context.span_id
    assert inventory_client.parent.span_id == order_server.context.span_id
    assert entries["inventory-service"].parent.span_id == inventory_client.context.span_id


@pytest.mark.asyncio
async def test_correlated_logs_and_sensitive_values_are_not_recorded() -> None:
    spans = InMemorySpanExporter()
    logs = InMemoryLogRecordExporter()
    stream = io.StringIO()
    payment_runtime = runtime(
        "payment-service", spans, logs, InMemoryMetricReader(), stream
    )
    payment = create_payment_app(
        PaymentSettings(app_environment="test"), telemetry_runtime=payment_runtime
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=payment), base_url="http://payment-service"
    ) as client:
        response = await client.post(
            "/payments",
            json={"amount": 9876.54},
            headers={"Authorization": "Bearer do-not-record-this"},
        )
    assert response.status_code == 200
    exported = logs.get_finished_logs()
    correlated = next(item for item in exported if item.log_record.body == "payment.completed")
    assert correlated.log_record.trace_id != 0
    assert correlated.log_record.span_id != 0
    console_record = json.loads(stream.getvalue().strip())
    assert console_record["trace_id"] == f"{correlated.log_record.trace_id:032x}"
    assert console_record["span_id"] == f"{correlated.log_record.span_id:016x}"
    serialized = stream.getvalue() + repr(exported) + repr(spans.get_finished_spans())
    assert "do-not-record-this" not in serialized
    assert "9876.54" not in serialized


@pytest.mark.asyncio
async def test_request_error_and_duration_metrics_record_observations() -> None:
    spans = InMemorySpanExporter()
    logs = InMemoryLogRecordExporter()
    metrics = InMemoryMetricReader()
    payment_runtime = runtime("payment-service", spans, logs, metrics)
    settings = PaymentSettings(
        app_environment="test", fault_injection_enabled=True, fault_max_duration_seconds=5
    )
    payment = create_payment_app(settings, telemetry_runtime=payment_runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=payment), base_url="http://payment-service"
    ) as client:
        normal = await client.post("/payments", json={"amount": 100.0})
        armed = await client.post(
            "/__faults", json={"mode": "errors", "duration_seconds": 1.0}
        )
        failed = await client.post("/payments", json={"amount": 100.0})
    assert (normal.status_code, armed.status_code, failed.status_code) == (200, 200, 500)
    values = metric_values(metrics)
    assert values[REQUESTS_METRIC][0] == 2
    assert values[ERRORS_METRIC][0] == 1
    assert values[DURATION_METRIC][0] == 2
    assert values[DURATION_METRIC][1] >= 0


@pytest.mark.asyncio
async def test_telemetry_can_be_disabled_without_changing_business_behavior() -> None:
    disabled = configure_telemetry(telemetry_settings("payment-service", enabled=False))
    assert disabled.tracer_provider is None
    assert disabled.meter_provider is None
    payment = create_payment_app(
        PaymentSettings(app_environment="test"), telemetry_runtime=disabled
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=payment), base_url="http://payment-service"
    ) as client:
        response = await client.post("/payments", json={"amount": 100.0})
    assert response.status_code == 200
