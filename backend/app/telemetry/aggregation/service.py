import math
from datetime import UTC, datetime, timedelta

from app.models.detection import (
    ServiceKey,
    ServiceMetricBucket,
    TimeRange,
    deterministic_id,
)
from app.models.telemetry import (
    QueryMetadata,
    ServiceReference,
    TelemetryQueryResult,
    TelemetrySpan,
    utc_timestamp_to_ns,
)

EXCLUDED_ROUTES = {
    "/health",
    "/healthz",
    "/ready",
    "/readyz",
    "/live",
    "/livez",
    "/metrics",
    "/docs",
    "/openapi.json",
}
EXCLUDED_PREFIXES = ("/admin", "/internal", "/__faults")
KNOWN_BUSINESS_NAMES = {"POST /orders", "POST /payments", "POST /reserve"}


def utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def service_key(reference: ServiceReference) -> ServiceKey:
    return ServiceKey(
        service_id=deterministic_id(
            "svc",
            [reference.namespace, reference.environment, reference.name],
        ),
        namespace=reference.namespace,
        environment=reference.environment,
        name=reference.name,
    )


def minute_window(value: datetime) -> tuple[datetime, datetime]:
    start = value.astimezone(UTC).replace(second=0, microsecond=0)
    return start, start + timedelta(minutes=1)


def route_is_excluded(route: str) -> bool:
    if route in EXCLUDED_ROUTES:
        return True
    return any(route == prefix or route.startswith(f"{prefix}/") for prefix in EXCLUDED_PREFIXES)


def nearest_rank_p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(0.95 * len(ordered)))
    return ordered[rank - 1]


def eligible_span(
    span: TelemetrySpan,
    *,
    service: ServiceReference,
    window_start_ns: int,
    window_end_ns: int,
    source_visible_ns: int,
) -> tuple[bool, str | None]:
    if span.kind != "SERVER":
        return False, None
    if (
        span.service.namespace != service.namespace
        or span.service.environment != service.environment
        or span.service.name != service.name
    ):
        return False, None
    end_ns = utc_timestamp_to_ns(span.end_time)
    if not window_start_ns <= end_ns < window_end_ns:
        return False, None
    if end_ns > source_visible_ns + 30_000_000_000:
        return False, "clock_skew"
    route = span.http_route
    if route is not None and route_is_excluded(route):
        return False, None
    if route is None and span.name not in KNOWN_BUSINESS_NAMES:
        return False, "invalid_span"
    if span.http_status_code is None and span.status != "ERROR":
        return False, "missing_http_status"
    return True, None


def aggregate_minute(
    service: ServiceReference,
    window_start: datetime,
    spans: TelemetryQueryResult[TelemetrySpan],
    *,
    computed_at: datetime,
    finalized: bool,
    aggregation_version: str = "1.0.0",
    minimum_samples: int = 20,
    sampling_fraction: float | None = 1.0,
) -> ServiceMetricBucket:
    start, end = minute_window(window_start)
    if start != window_start.astimezone(UTC):
        raise ValueError("window start must be UTC-minute aligned")
    start_ns = int(start.timestamp()) * 1_000_000_000
    end_ns = start_ns + 60_000_000_000
    visible_ns = int(computed_at.astimezone(UTC).timestamp() * 1_000_000_000)
    included: list[TelemetrySpan] = []
    rejection_reasons: list[str] = []
    for span in spans.items:
        include, reason = eligible_span(
            span,
            service=service,
            window_start_ns=start_ns,
            window_end_ns=end_ns,
            source_visible_ns=visible_ns,
        )
        if include:
            included.append(span)
        elif reason is not None:
            rejection_reasons.append(reason)

    durations = [span.duration_ms for span in included]
    request_count = len(included)
    error_count = sum(
        span.status == "ERROR"
        or (span.http_status_code is not None and span.http_status_code >= 500)
        for span in included
    )
    reasons: list[str] = list(dict.fromkeys(rejection_reasons))
    if spans.metadata.duplicate_conflict_count:
        reasons.append("duplicate_conflict")
    if spans.metadata.malformed_count and "invalid_span" not in reasons:
        reasons.append("invalid_span")
    if spans.metadata.partial and "query_partial" not in reasons:
        reasons.append("query_partial")
    if spans.metadata.truncated and "truncated" not in reasons:
        reasons.append("truncated")
    if sampling_fraction is None:
        reasons.append("pipeline_stale")
    elif sampling_fraction < 1:
        reasons.append("sampling_enabled")

    integrity_reasons = {
        "clock_skew",
        "duplicate_conflict",
        "invalid_span",
        "missing_http_status",
        "query_partial",
        "sampling_enabled",
        "truncated",
    }
    if sampling_fraction is None:
        quality = "unknown"
    elif any(reason in integrity_reasons for reason in reasons):
        quality = "partial"
    elif request_count < minimum_samples:
        quality = "insufficient"
        reasons.append("no_spans" if request_count == 0 else "low_sample_count")
    else:
        quality = "complete"
    reasons = list(dict.fromkeys(reasons))
    service_value = service_key(service)
    start_text = utc(start)
    end_text = utc(end)
    computed_text = utc(computed_at)
    return ServiceMetricBucket(
        schema_version="1.0.0",
        bucket_id=deterministic_id(
            "bucket",
            [service_value.service_id, str(start_ns), aggregation_version],
        ),
        service=service_value,
        window=TimeRange(start=start_text, end=end_text),
        bucket_time=start_text,
        request_count=request_count,
        error_count=error_count,
        error_rate=(error_count / request_count if request_count else None),
        latency_mean_ms=(sum(durations) / request_count if request_count else None),
        latency_p95_ms=nearest_rank_p95(durations),
        source_count=request_count,
        invalid_span_count=len(rejection_reasons) + spans.metadata.malformed_count,
        late_span_count=0,
        quality_status=quality,
        quality_reasons=reasons,
        eligible_for_detection=bool(
            finalized and quality == "complete" and request_count >= minimum_samples
        ),
        source_kind="server_spans",
        aggregation_version=aggregation_version,
        sampling_fraction=sampling_fraction,
        computed_at=computed_text,
        finalized_at=computed_text if finalized else None,
        source_visible_through=computed_text,
    )


def empty_query_result() -> TelemetryQueryResult[TelemetrySpan]:
    return TelemetryQueryResult[TelemetrySpan](
        items=[],
        metadata=QueryMetadata(
            partial=False,
            truncated=False,
            reasons=[],
            returned_count=0,
            matched_count=0,
        ),
    )
