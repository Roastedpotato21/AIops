from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.config import Settings
from app.models.telemetry import ServiceReference
from app.opensearch.query import OpenSearchQueryFailure
from app.repositories.telemetry import TelemetryRepository, TelemetryRepositoryError
from app.telemetry.adapters import (
    MalformedTelemetryDocument,
    map_log_document,
    map_metric_document,
    map_native_dependency_document,
    map_span_document,
)

NOW = datetime(2026, 9, 19, 16, 30, tzinfo=UTC)
TRACE_ID = "a" * 32
RESOURCE = {
    "attributes": {
        "service.namespace": "demo-shop",
        "deployment.environment.name": "development",
        "service.instance.id": "instance-1",
        "service.name": "order-service",
        "service.version": "0.3.0",
    }
}


def settings() -> Settings:
    return Settings(
        opensearch_username="runtime",
        opensearch_password="not-a-real-password",
    )


def response(hits: list[dict[str, Any]], *, total: int | None = None, failed: int = 0):
    return {
        "timed_out": False,
        "_shards": {"failed": failed},
        "hits": {
            "total": {"value": len(hits) if total is None else total, "relation": "eq"},
            "hits": hits,
        },
    }


def service(name: str) -> ServiceReference:
    return ServiceReference(
        namespace="demo-shop",
        environment="development",
        name=name,
    )


def span_hit(
    span_id: str,
    *,
    name: str,
    kind: str,
    service_name: str,
    parent_span_id: str | None = None,
    status: int = 200,
    document_id: str | None = None,
) -> dict[str, Any]:
    resource = deepcopy(RESOURCE)
    resource["attributes"]["service.name"] = service_name
    return {
        "_index": "otel-v1-apm-span-000001",
        "_id": document_id or f"{TRACE_ID}-{span_id}",
        "_source": {
            "resource": resource,
            "serviceName": service_name,
            "traceId": TRACE_ID,
            "spanId": span_id,
            "parentSpanId": parent_span_id,
            "name": name,
            "kind": kind,
            "startTime": "2026-09-19T16:00:00.000000000Z",
            "endTime": "2026-09-19T16:00:00.010000000Z",
            "durationInNanos": 10_000_000,
            "status": {"code": 0},
            "attributes": {
                "http.method": "POST",
                "http.route": name,
                "http.status_code": status,
            },
        },
    }


def trace_hits() -> list[dict[str, Any]]:
    return [
        span_hit("1" * 16, name="/orders", kind="SPAN_KIND_SERVER", service_name="order-service"),
        span_hit(
            "2" * 16,
            name="payment call",
            kind="SPAN_KIND_CLIENT",
            service_name="order-service",
            parent_span_id="1" * 16,
        ),
        span_hit(
            "3" * 16,
            name="/payments",
            kind="SPAN_KIND_SERVER",
            service_name="payment-service",
            parent_span_id="2" * 16,
        ),
        span_hit(
            "4" * 16,
            name="inventory call",
            kind="SPAN_KIND_CLIENT",
            service_name="order-service",
            parent_span_id="1" * 16,
        ),
        span_hit(
            "5" * 16,
            name="/reserve",
            kind="SPAN_KIND_SERVER",
            service_name="inventory-service",
            parent_span_id="4" * 16,
        ),
    ]


class FakeSearchClient:
    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((index, body))
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


def test_adapters_normalize_real_native_documents() -> None:
    log = map_log_document(
        {
            "_index": "aiops-logs-2026.09.19",
            "_id": "log-1",
            "_source": {
                "resource": RESOURCE,
                "time": "2026-09-19T16:00:00.123456789Z",
                "observedTimestamp": "2026-09-19T16:00:00.223456789Z",
                "severityText": "INFO",
                "body": "order.completed",
                "traceId": TRACE_ID,
                "spanId": "1" * 16,
                "attributes": {"event": "order.completed", "secret": "excluded"},
            },
        }
    )
    span = map_span_document(trace_hits()[0])
    metric = map_metric_document(
        {
            "_index": "aiops-metrics-raw-2026.09.19",
            "_id": "metric-1",
            "_source": {
                "resource": RESOURCE,
                "name": "demo.http.server.duration",
                "description": "request duration",
                "unit": "ms",
                "kind": "HISTOGRAM",
                "aggregationTemporality": "AGGREGATION_TEMPORALITY_CUMULATIVE",
                "startTime": "2026-09-19T15:59:00.000000000Z",
                "time": "2026-09-19T16:00:00.000000000Z",
                "count": 2,
                "sum": 15.0,
                "min": 5.0,
                "max": 10.0,
                "explicitBounds": [5.0],
                "bucketCountsList": [0, 2],
                "attributes": {"http.route": "/orders", "secret": "excluded"},
            },
        }
    )

    assert log.service.name == "order-service"
    assert log.event == "order.completed"
    assert span.duration_ms == 10.0
    assert span.http_status_code == 200
    assert metric.histogram is not None
    assert metric.histogram.counts == [0, 2]
    assert metric.labels == {"http.route": "/orders"}


def test_adapter_rejects_conflicting_or_incomplete_identity() -> None:
    hit = trace_hits()[0]
    hit["_source"]["resource"]["attributes"]["deployment.environment"] = "production"
    with pytest.raises(MalformedTelemetryDocument, match="conflict"):
        map_span_document(hit)


def test_native_dependency_adapter_maps_only_registered_client_edges() -> None:
    edge = map_native_dependency_document(
        {
            "_index": "otel-v1-apm-service-map",
            "_id": "edge-1",
            "_source": {
                "serviceName": "order-service",
                "kind": "SPAN_KIND_CLIENT",
                "destination": {
                    "domain": "payment-service",
                    "resource": "POST /payments",
                },
                "traceGroupName": "POST /orders",
            },
        },
        services={
            "order-service": service("order-service"),
            "payment-service": service("payment-service"),
        },
        window_start="2026-09-19T16:00:00Z",
        window_end="2026-09-19T16:05:00Z",
        observed_at="2026-09-19T16:05:01Z",
    )

    assert edge.source_service.name == "order-service"
    assert edge.target_service.name == "payment-service"
    assert edge.source_kind == "native_service_map"
    assert edge.observed_trace_count is None


@pytest.mark.asyncio
async def test_trace_reconstruction_preserves_sibling_business_dependencies() -> None:
    client = FakeSearchClient([response(trace_hits()), response(trace_hits())])
    repository = TelemetryRepository(client, settings(), clock=lambda: NOW)

    trace_result = await repository.get_trace(
        TRACE_ID,
        start_time=NOW - timedelta(hours=1),
        end_time=NOW,
    )
    dependency_result = await repository.get_service_dependencies(
        None,
        NOW - timedelta(minutes=30),
        NOW,
    )

    assert [item.span_id for item in trace_result.items[0].spans] == [
        "1" * 16,
        "2" * 16,
        "3" * 16,
        "4" * 16,
        "5" * 16,
    ]
    edges = {
        (edge.source_service.name, edge.target_service.name)
        for edge in dependency_result.items
    }
    assert edges == {
        ("order-service", "payment-service"),
        ("order-service", "inventory-service"),
    }
    assert ("payment-service", "inventory-service") not in edges
    assert all(edge.source_kind == "trace_reconstruction" for edge in dependency_result.items)


@pytest.mark.asyncio
async def test_duplicate_spans_collapse_and_conflicts_are_reported() -> None:
    original = trace_hits()[0]
    duplicate = deepcopy(original)
    duplicate["_index"] = "otel-v1-apm-span-000002"
    conflicting = deepcopy(original)
    conflicting["_index"] = "otel-v1-apm-span-000003"
    conflicting["_source"]["name"] = "/orders-conflict"
    client = FakeSearchClient([response([conflicting, duplicate, original])])
    repository = TelemetryRepository(client, settings(), clock=lambda: NOW)

    result = await repository.search_spans(
        service("order-service"),
        NOW - timedelta(hours=1),
        NOW,
    )

    assert len(result.items) == 1
    assert result.metadata.duplicate_count == 1
    assert result.metadata.duplicate_conflict_count == 1
    assert result.metadata.partial is True
    assert result.metadata.reasons == ["duplicate_conflict"]


@pytest.mark.asyncio
async def test_malformed_partial_and_truncated_metadata_is_explicit() -> None:
    malformed = {"_index": "otel-v1-apm-span-000001", "_id": "bad", "_source": {}}
    client = FakeSearchClient(
        [response([trace_hits()[0], malformed], total=250, failed=1)]
    )
    repository = TelemetryRepository(client, settings(), clock=lambda: NOW)

    result = await repository.search_spans(
        service("order-service"),
        NOW - timedelta(hours=1),
        NOW,
        limit=1,
    )

    assert result.metadata.partial is True
    assert result.metadata.truncated is True
    assert result.metadata.malformed_count == 1
    assert set(result.metadata.reasons) == {"invalid_span", "query_partial", "truncated"}


@pytest.mark.asyncio
async def test_queries_are_bounded_and_use_only_configured_aliases() -> None:
    client = FakeSearchClient([response([])])
    repository = TelemetryRepository(client, settings(), clock=lambda: NOW)

    with pytest.raises(TelemetryRepositoryError) as error:
        await repository.search_logs(
            service("order-service"),
            NOW - timedelta(hours=25),
            NOW,
        )
    assert error.value.code == "invalid_argument"
    assert client.calls == []

    await repository.search_logs(
        service("order-service"),
        NOW - timedelta(minutes=5),
        NOW,
        limit=10,
    )
    index, body = client.calls[0]
    assert index == "aiops-logs"
    assert body["size"] == 11
    assert body["query"]["bool"]["filter"][0]["range"]["time"]["lt"].endswith("Z")


@pytest.mark.asyncio
async def test_opensearch_unavailable_is_safe_and_retryable() -> None:
    client = FakeSearchClient(error=OpenSearchQueryFailure("unavailable"))
    repository = TelemetryRepository(client, settings(), clock=lambda: NOW)

    with pytest.raises(TelemetryRepositoryError) as error:
        await repository.get_native_metrics(
            service("order-service"),
            NOW - timedelta(minutes=5),
            NOW,
        )

    assert str(error.value) == "Telemetry repository unavailable"
    assert error.value.code == "unavailable"
    assert error.value.retryable is True
    assert "password" not in str(error.value).lower()
