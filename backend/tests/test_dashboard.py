from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dashboard import router
from app.api.errors import install_error_handlers
from app.detection.registry import registered_specs
from app.models.detection import ServiceMetricBucket, TimeRange, deterministic_id
from app.models.telemetry import (
    QueryMetadata,
    ServiceReference,
    SourceDocument,
    TelemetryQueryResult,
    TelemetryService,
    TelemetrySpan,
    TelemetryTrace,
)
from app.repositories.telemetry import TelemetryRepositoryError


def stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


SERVICE = registered_specs()[0].service
NOW = datetime.now(UTC).replace(second=0, microsecond=0)
START = NOW - timedelta(minutes=2)
END = START + timedelta(minutes=1)
BUCKET = ServiceMetricBucket(
    schema_version="1.0.0",
    bucket_id=deterministic_id(
        "bucket", [SERVICE.service_id, str(int(START.timestamp() * 1_000_000_000)), "1.0.0"]
    ),
    service=SERVICE,
    window=TimeRange(start=stamp(START), end=stamp(END)),
    bucket_time=stamp(START),
    request_count=100,
    error_count=0,
    error_rate=0.0,
    latency_mean_ms=10.0,
    latency_p95_ms=20.0,
    source_count=100,
    invalid_span_count=0,
    late_span_count=0,
    quality_status="complete",
    quality_reasons=[],
    eligible_for_detection=True,
    source_kind="server_spans",
    aggregation_version="1.0.0",
    sampling_fraction=1.0,
    computed_at=stamp(END + timedelta(seconds=90)),
    finalized_at=stamp(END + timedelta(seconds=90)),
    source_visible_through=stamp(END + timedelta(seconds=90)),
)


class IncidentRepository:
    async def recent_buckets(self, service_id: str, start: str, limit: int = 5):
        return [BUCKET] if service_id == SERVICE.service_id else []

    async def list_incidents(self, **kwargs):
        return []

    async def metric_buckets(self, service_ids, start: str, end: str, *, limit: int):
        return [BUCKET] if SERVICE.service_id in service_ids else []


class TelemetryRepository:
    async def get_service_dependencies(self, service, start, end, *, limit: int):
        return TelemetryQueryResult(
            items=[],
            metadata=QueryMetadata(
                partial=False,
                truncated=False,
                reasons=[],
                returned_count=0,
                matched_count=0,
            ),
        )

    async def get_native_metrics(self, service, start, end, *, metric_names, limit: int):
        return TelemetryQueryResult(
            items=[],
            metadata=QueryMetadata(
                partial=False,
                truncated=False,
                reasons=[],
                returned_count=0,
                matched_count=0,
            ),
        )

    async def get_trace(self, trace_id, *, start_time, end_time, max_spans):
        span_end = START + timedelta(milliseconds=10)
        span = TelemetrySpan(
            source=SourceDocument(index="otel-v1-apm-span-000001", document_id="span-1"),
            service=TelemetryService(
                service_id=SERVICE.service_id,
                namespace=SERVICE.namespace,
                environment=SERVICE.environment,
                name=SERVICE.name,
                instance_id="test-instance",
            ),
            trace_id=trace_id,
            span_id="1" * 16,
            parent_span_id=None,
            name="POST /orders",
            kind="SERVER",
            start_time=stamp(START),
            end_time=stamp(span_end),
            duration_ns=10_000_000,
            duration_ms=10.0,
            status="OK",
            http_method="POST",
            http_route="/orders",
            http_status_code=200,
            content_sha256="a" * 64,
        )
        trace = TelemetryTrace(
            trace_id=trace_id,
            spans=[span],
            services=[
                ServiceReference(
                    namespace=SERVICE.namespace,
                    environment=SERVICE.environment,
                    name=SERVICE.name,
                )
            ],
            start_time=span.start_time,
            end_time=span.end_time,
            root_present=True,
            missing_parent_count=0,
            has_error=False,
        )
        return TelemetryQueryResult(
            items=[trace],
            metadata=QueryMetadata(
                partial=False,
                truncated=False,
                reasons=[],
                returned_count=1,
                matched_count=1,
            ),
        )


def client(incident_repository=None) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(router)
    app.state.incident_repository = incident_repository or IncidentRepository()
    app.state.telemetry_repository = TelemetryRepository()
    return TestClient(app)


def test_overview_and_services_preserve_unknown_health_and_exact_shapes() -> None:
    api = client()
    overview = api.get("/api/v1/overview").json()["result"]
    services = api.get("/api/v1/services").json()["result"]["items"]

    assert set(overview) == {
        "overall_health",
        "service_counts",
        "active_incident_count",
        "recent_incidents",
        "components",
    }
    assert overview["overall_health"] == "unknown"
    assert len(services) == 3
    observed = next(
        item for item in services if item["service"]["service_id"] == SERVICE.service_id
    )
    assert set(observed) == {"service", "health", "last_seen_at", "active_incident_count"}
    assert observed["health"]["state"] == "unknown"
    assert observed["health"]["quality_reasons"] == ["detector_unready"]
    assert observed["health"]["telemetry_age_seconds"] is None


def test_service_detail_metrics_dependencies_and_scope() -> None:
    api = client()
    detail = api.get(f"/api/v1/services/{SERVICE.service_id}").json()["result"]
    metrics = api.get(
        f"/api/v1/services/{SERVICE.service_id}/metrics",
        params={"start": stamp(START), "end": stamp(NOW), "include_native": "true"},
    ).json()["result"]
    dependencies = api.get(
        f"/api/v1/services/{SERVICE.service_id}/dependencies",
        params={"start": stamp(START), "end": stamp(NOW)},
    ).json()["result"]
    outside = api.get(
        "/api/v1/services", params={"namespace": "another", "environment": "development"}
    ).json()["result"]

    assert detail["latest_bucket"]["bucket_id"] == BUCKET.bucket_id
    assert metrics["buckets"]["items"][0]["latency_p95_ms"] == 20.0
    assert metrics["native_points"] == []
    assert dependencies["edges"]["items"] == []
    assert outside["items"] == []


def test_dependency_failure_is_safe_503() -> None:
    class UnavailableRepository(IncidentRepository):
        async def recent_buckets(self, service_id: str, start: str, limit: int = 5):
            raise TelemetryRepositoryError("unavailable", retryable=True)

    response = client(UnavailableRepository()).get("/api/v1/overview")
    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "dependency_unavailable",
        "message": "A required dependency is unavailable",
        "retryable": True,
        "details": [],
        "active_investigation_id": None,
    }


def test_bounded_trace_endpoint_returns_typed_scope_safe_trace() -> None:
    trace_id = "a" * 32
    response = client().get(
        f"/api/v1/traces/{trace_id}",
        params={
            "service_id": SERVICE.service_id,
            "start": stamp(START - timedelta(minutes=1)),
            "end": stamp(END + timedelta(minutes=1)),
            "max_spans": 10,
        },
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["trace"]["trace_id"] == trace_id
    assert result["trace"]["spans"][0]["service"]["service_id"] == SERVICE.service_id
    assert result["evidence_id"] is None
    assert result["out_of_scope_span_count"] == 0


def test_trace_validation_uses_safe_contract_error_envelope() -> None:
    response = client().get(
        f"/api/v1/traces/{'a' * 32}",
        params={
            "service_id": SERVICE.service_id,
            "start": stamp(START),
            "end": stamp(END),
            "max_spans": 201,
        },
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["retryable"] is False
    assert error["details"][0]["field"] == "query.max_spans"


def test_unknown_query_field_is_rejected() -> None:
    response = client().get("/api/v1/services", params={"query": "match_all"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
