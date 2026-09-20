from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Path, Query, Request

from app.api.strict import StrictQueryRoute
from app.detection.registry import registered_specs
from app.incidents.evidence import service_key_from_reference, span_snapshot
from app.models.dashboard import (
    ComponentStatus,
    DependenciesResponse,
    MetricLabel,
    MetricsResponse,
    NativeHistogramValue,
    NativeMetricSnapshot,
    NativeScalarValue,
    Overview,
    ServiceCounts,
    ServiceDetail,
    ServiceHealth,
    ServiceSummary,
    TraceResponse,
)
from app.models.detection import ServiceKey, TimeRange
from app.models.incidents import ApiResponse, Coverage, Freshness, Page, TraceSnapshot
from app.models.telemetry import NativeMetric, ServiceReference
from app.repositories.telemetry import TelemetryRepositoryError

router = APIRouter(prefix="/api/v1", tags=["dashboard"], route_class=StrictQueryRoute)


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _valid_range(start: datetime, end: datetime, maximum: timedelta) -> bool:
    return (
        start.tzinfo is not None
        and end.tzinfo is not None
        and start.utcoffset() == timedelta(0)
        and end.utcoffset() == timedelta(0)
        and start < end
        and end - start <= maximum
        and end <= datetime.now(UTC) + timedelta(seconds=30)
    )


LABEL_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$"
NATIVE_METRIC_NAMES = {
    "demo.http.server.requests",
    "demo.http.server.errors",
    "demo.http.server.duration",
}
NATIVE_LABEL_NAMES = {"http.request.method", "http.route", "http.response.status_code"}


def _services(namespace: str | None = None, environment: str | None = None) -> list[ServiceKey]:
    return sorted(
        {
            spec.service.service_id: spec.service
            for spec in registered_specs()
            if (namespace is None or spec.service.namespace == namespace)
            and (environment is None or spec.service.environment == environment)
        }.values(),
        key=lambda item: item.service_id,
    )


def _service(service_id: str) -> ServiceKey:
    found = next((item for item in _services() if item.service_id == service_id), None)
    if found is None:
        raise HTTPException(404, "not_found")
    return found


def _native_snapshot(metric: NativeMetric) -> NativeMetricSnapshot:
    event = datetime.fromisoformat(metric.event_time.replace("Z", "+00:00"))
    service = ServiceKey(
        service_id=metric.service.service_id,
        namespace=metric.service.namespace,
        environment=metric.service.environment,
        name=metric.service.name,
    )
    if metric.histogram is None:
        value = NativeScalarValue(value=metric.value)
    else:
        value = NativeHistogramValue(
            count=metric.histogram.count,
            sum=metric.histogram.sum,
            bounds=metric.histogram.bounds,
            counts=metric.histogram.counts,
        )
    return NativeMetricSnapshot(
        service=service,
        name=metric.name,
        unit=metric.unit,
        window=TimeRange(start=_utc(event), end=_utc(event + timedelta(microseconds=1))),
        metric_type=metric.metric_type,
        temporality=metric.temporality,
        attribute_labels=[
            MetricLabel(key=key, value=value)
            for key, value in sorted(metric.labels.items())
            if key in NATIVE_LABEL_NAMES
        ][:16],
        value=value,
    )


def _envelope(result, *, latest: str | None = None, partial: bool = False):
    now = datetime.now(UTC)
    age = None
    if latest:
        age = max(
            0.0, (now - datetime.fromisoformat(latest.replace("Z", "+00:00"))).total_seconds()
        )
    return ApiResponse(
        result=result,
        request_id=str(uuid4()),
        freshness=Freshness(
            generated_at=_utc(now),
            latest_source_at=latest,
            age_seconds=age,
            state="unknown" if latest is None else ("stale" if age and age > 300 else "fresh"),
        ),
        coverage=Coverage(
            status="partial" if partial else "complete",
            reasons=["detector_unready"] if partial else [],
            message="Detector and worker public status is not available" if partial else None,
        ),
    )


async def _summaries(
    request: Request, namespace: str, environment: str
) -> list[ServiceSummary]:
    now = datetime.now(UTC)
    result = []
    for service in _services(namespace, environment):
        buckets = await request.app.state.incident_repository.recent_buckets(
            service.service_id, _utc(now - timedelta(hours=24)), limit=1
        )
        incidents = await request.app.state.incident_repository.list_incidents(
            namespace=service.namespace,
            environment=service.environment,
            state=None,
            severity=None,
            service_id=service.service_id,
            start=_utc(now - timedelta(days=30)),
            end=_utc(now + timedelta(seconds=1)),
            limit=100,
        )
        active = [item for item in incidents if item.state in ("open", "recovering")]
        bucket = buckets[0] if buckets else None
        age = (
            max(
                0.0,
                (
                    now - datetime.fromisoformat(bucket.window.end.replace("Z", "+00:00"))
                ).total_seconds(),
            )
            if bucket
            else None
        )
        if bucket is None or age is None or age > 300 or bucket.quality_status != "complete":
            state = "unknown"
            reason = "Fresh complete feature data is unavailable"
            quality = "unknown"
            reasons = ["pipeline_stale"] if age is not None and age > 300 else ["detector_unready"]
        else:
            state = "unknown"
            reason = "Detector readiness is not exposed; healthy cannot be inferred"
            quality, reasons = "unknown", ["detector_unready"]
        health = ServiceHealth(
            service=service,
            state=state,
            reason=reason,
            assessed_at=_utc(now),
            latest_bucket_end=bucket.window.end if bucket else None,
            telemetry_age_seconds=None,
            active_incident_ids=[item.incident_id for item in active],
            quality_status=quality,
            quality_reasons=reasons,
        )
        result.append(
            ServiceSummary(
                service=service,
                health=health,
                last_seen_at=bucket.window.end if bucket else None,
                active_incident_count=len(active),
            )
        )
    return result


@router.get("/overview")
async def overview(
    request: Request,
    namespace: Annotated[str, Query(pattern=LABEL_PATTERN)] = "demo-shop",
    environment: Annotated[str, Query(pattern=LABEL_PATTERN)] = "development",
) -> ApiResponse[Overview]:
    try:
        services = await _summaries(request, namespace, environment)
        incidents = await request.app.state.incident_repository.list_incidents(
            namespace=namespace,
            environment=environment,
            state=None,
            severity=None,
            service_id=None,
            start=_utc(datetime.now(UTC) - timedelta(days=1)),
            end=_utc(datetime.now(UTC) + timedelta(seconds=1)),
            limit=100,
        )
    except TelemetryRepositoryError:
        raise HTTPException(503, "dependency_unavailable") from None
    counts = {
        state: sum(item.health.state == state for item in services)
        for state in ("healthy", "degraded", "unhealthy", "unknown")
    }
    overall = (
        "unknown"
        if counts["unknown"]
        else (
            "unhealthy"
            if counts["unhealthy"]
            else ("degraded" if counts["degraded"] else "healthy")
        )
    )
    now = _utc(datetime.now(UTC))
    return _envelope(
        Overview(
            overall_health=overall,
            service_counts=ServiceCounts(**counts),
            active_incident_count=sum(item.state in ("open", "recovering") for item in incidents),
            recent_incidents=incidents[:10],
            components=[
                ComponentStatus(name="opensearch", state="healthy", checked_at=now),
                ComponentStatus(
                    name="detectors",
                    state="unknown",
                    checked_at=now,
                    reason="Public detector status unavailable",
                ),
                ComponentStatus(
                    name="aggregation",
                    state="unknown",
                    checked_at=now,
                    reason="Public worker status unavailable",
                ),
                ComponentStatus(
                    name="incident",
                    state="unknown",
                    checked_at=now,
                    reason="Public worker status unavailable",
                ),
                ComponentStatus(
                    name="investigation",
                    state="unknown",
                    checked_at=now,
                    reason="Public worker status unavailable",
                ),
            ],
        ),
        latest=max((item.last_seen_at for item in services if item.last_seen_at), default=None),
        partial=True,
    )


@router.get("/services")
async def services(
    request: Request,
    namespace: Annotated[str, Query(pattern=LABEL_PATTERN)] = "demo-shop",
    environment: Annotated[str, Query(pattern=LABEL_PATTERN)] = "development",
    health: Literal["healthy", "degraded", "unhealthy", "unknown"] | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
):
    if cursor is not None:
        raise HTTPException(400, "invalid_cursor")
    try:
        items = await _summaries(request, namespace, environment)
    except TelemetryRepositoryError:
        raise HTTPException(503, "dependency_unavailable") from None
    if health:
        items = [item for item in items if item.health.state == health]
    return _envelope(
        Page(items=items[:limit], has_more=len(items) > limit),
        latest=max((item.last_seen_at for item in items if item.last_seen_at), default=None),
        partial=True,
    )


@router.get("/services/{service_id}")
async def service_detail(
    request: Request, service_id: Annotated[str, Path(pattern=r"^svc_[0-9a-f]{64}$")]
):
    _service(service_id)
    service = _service(service_id)
    try:
        summaries = await _summaries(request, service.namespace, service.environment)
        buckets = await request.app.state.incident_repository.recent_buckets(
            service_id, _utc(datetime.now(UTC) - timedelta(hours=24)), limit=1
        )
    except TelemetryRepositoryError:
        raise HTTPException(503, "dependency_unavailable") from None
    summary = next(item for item in summaries if item.service.service_id == service_id)
    return _envelope(
        ServiceDetail(
            summary=summary,
            instances=[],
            detectors=[],
            latest_bucket=buckets[0] if buckets else None,
            dependency_count=None,
        ),
        latest=summary.last_seen_at,
        partial=True,
    )


@router.get("/services/{service_id}/metrics")
async def service_metrics(
    request: Request,
    service_id: Annotated[str, Path(pattern=r"^svc_[0-9a-f]{64}$")],
    start: datetime | None = None,
    end: datetime | None = None,
    features: Annotated[
        list[Literal["latency_p95_ms", "error_rate"]] | None,
        Query(min_length=1, max_length=2),
    ] = None,
    include_native: bool = False,
    limit: Annotated[int, Query(ge=1, le=120)] = 60,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
):
    if cursor is not None:
        raise HTTPException(400, "invalid_cursor")
    service = _service(service_id)
    stop = end or datetime.now(UTC)
    begin = start or stop - timedelta(hours=1)
    if not _valid_range(begin, stop, timedelta(hours=24)):
        raise HTTPException(422, "invalid metric time range")
    try:
        buckets = await request.app.state.incident_repository.metric_buckets(
            [service_id], _utc(begin), _utc(stop), limit=limit + 1
        )
        native_result = (
            await request.app.state.telemetry_repository.get_native_metrics(
                ServiceReference(
                    namespace=service.namespace,
                    environment=service.environment,
                    name=service.name,
                ),
                begin,
                stop,
                metric_names=sorted(NATIVE_METRIC_NAMES),
                limit=20,
            )
            if include_native
            else None
        )
    except TelemetryRepositoryError:
        raise HTTPException(503, "dependency_unavailable") from None
    native_points = (
        [_native_snapshot(item) for item in native_result.items] if native_result else []
    )
    return _envelope(
        MetricsResponse(
            service=service,
            window=TimeRange(start=_utc(begin), end=_utc(stop)),
            requested_features=features or ["latency_p95_ms", "error_rate"],
            buckets=Page(items=buckets[:limit], has_more=len(buckets) > limit),
            native_points=native_points,
        ),
        latest=buckets[-1].window.end if buckets else None,
    )


@router.get("/services/{service_id}/dependencies")
async def service_dependencies(
    request: Request,
    service_id: Annotated[str, Path(pattern=r"^svc_[0-9a-f]{64}$")],
    start: datetime | None = None,
    end: datetime | None = None,
    direction: Literal["upstream", "downstream", "both"] = "both",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
):
    if cursor is not None:
        raise HTTPException(400, "invalid_cursor")
    service = _service(service_id)
    stop = end or datetime.now(UTC)
    begin = start or stop - timedelta(minutes=15)
    if not _valid_range(begin, stop, timedelta(hours=1)):
        raise HTTPException(422, "invalid dependency time range")
    try:
        result = await request.app.state.telemetry_repository.get_service_dependencies(
            service, begin, stop, limit=limit
        )
    except TelemetryRepositoryError:
        raise HTTPException(503, "dependency_unavailable") from None
    edges = [
        item
        for item in result.items
        if direction == "both"
        or (direction == "downstream" and item.source_service.service_id == service_id)
        or (direction == "upstream" and item.target_service.service_id == service_id)
    ]
    return _envelope(
        DependenciesResponse(
            service=service,
            window=TimeRange(start=_utc(begin), end=_utc(stop)),
            edges=Page(items=edges[:limit], has_more=len(edges) > limit),
        ),
        latest=max((item.observed_at for item in edges), default=None),
        partial=result.metadata.partial or result.metadata.truncated,
    )


@router.get("/traces/{trace_id}")
async def trace_detail(
    request: Request,
    trace_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")],
    service_id: Annotated[str, Query(pattern=r"^svc_[0-9a-f]{64}$")],
    start: datetime,
    end: datetime,
    max_spans: Annotated[int, Query(ge=1, le=200)] = 100,
) -> ApiResponse[TraceResponse]:
    requested_service = _service(service_id)
    if not _valid_range(start, end, timedelta(minutes=30)):
        raise HTTPException(422, "invalid trace time range")
    try:
        result = await request.app.state.telemetry_repository.get_trace(
            trace_id,
            start_time=start,
            end_time=end,
            max_spans=max_spans,
        )
    except TelemetryRepositoryError:
        raise HTTPException(503, "dependency_unavailable") from None
    if not result.items:
        raise HTTPException(404, "not_found")
    trace = result.items[0]
    if not any(span.service.service_id == service_id for span in trace.spans):
        raise HTTPException(404, "not_found")
    allowed_ids = {
        service.service_id
        for service in _services(requested_service.namespace, requested_service.environment)
    }
    authorized = [span for span in trace.spans if span.service.service_id in allowed_ids]
    removed = len(trace.spans) - len(authorized)
    if not authorized:
        raise HTTPException(404, "not_found")
    span_ids = {span.span_id for span in authorized}
    missing_parents = sum(
        span.parent_span_id is not None and span.parent_span_id not in span_ids
        for span in authorized
    )
    snapshot = TraceSnapshot(
        trace_id=trace.trace_id,
        window=TimeRange(
            start=min(span.start_time for span in authorized),
            end=max(span.end_time for span in authorized),
        ),
        services=sorted(
            {
                span.service.service_id: service_key_from_reference(span.service)
                for span in authorized
            }.values(),
            key=lambda item: item.service_id,
        ),
        spans=[span_snapshot(span) for span in authorized],
        root_present=any(span.parent_span_id is None for span in authorized),
        truncated=result.metadata.truncated or removed > 0,
        missing_parent_count=missing_parents,
        observed_span_count=result.metadata.matched_count,
    )
    return _envelope(
        TraceResponse(
            trace=snapshot,
            evidence_id=None,
            out_of_scope_span_count=removed,
        ),
        latest=snapshot.window.end,
        partial=result.metadata.partial or result.metadata.truncated or removed > 0,
    )
