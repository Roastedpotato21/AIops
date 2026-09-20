from datetime import UTC, datetime, timedelta

import pytest

from app.models.detection import deterministic_id
from app.models.telemetry import (
    QueryMetadata,
    ServiceReference,
    SourceDocument,
    TelemetryQueryResult,
    TelemetryService,
    TelemetrySpan,
)
from app.telemetry.aggregation.service import aggregate_minute, nearest_rank_p95
from app.workers.aggregation import processing_range

WINDOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
SERVICE = ServiceReference(
    namespace="demo-shop",
    environment="development",
    name="payment-service",
)


def span(
    number: int,
    *,
    kind: str = "SERVER",
    route: str | None = "/payments",
    status: str = "OK",
    http_status: int | None = 200,
    duration_ms: int = 10,
    end_offset_seconds: int = 10,
) -> TelemetrySpan:
    start = WINDOW + timedelta(seconds=end_offset_seconds, milliseconds=-duration_ms)
    end = WINDOW + timedelta(seconds=end_offset_seconds)
    service_id = deterministic_id(
        "svc",
        [SERVICE.namespace, SERVICE.environment, SERVICE.name],
    )
    return TelemetrySpan(
        source=SourceDocument(index="spans", document_id=f"span-{number}"),
        service=TelemetryService(
            service_id=service_id,
            namespace=SERVICE.namespace,
            environment=SERVICE.environment,
            name=SERVICE.name,
            instance_id="payment-1",
            version="0.3.0",
        ),
        trace_id=f"{number + 1:032x}",
        span_id=f"{number + 1:016x}",
        parent_span_id=None,
        name="POST /payments",
        kind=kind,
        start_time=start.isoformat().replace("+00:00", "Z"),
        end_time=end.isoformat().replace("+00:00", "Z"),
        duration_ns=duration_ms * 1_000_000,
        duration_ms=float(duration_ms),
        status=status,
        http_method="POST",
        http_route=route,
        http_status_code=http_status,
        content_sha256=f"{number + 1:064x}",
    )


def result(items: list[TelemetrySpan], *, partial: bool = False):
    return TelemetryQueryResult[TelemetrySpan](
        items=items,
        metadata=QueryMetadata(
            partial=partial,
            truncated=False,
            reasons=["query_partial"] if partial else [],
            returned_count=len(items),
            matched_count=len(items),
        ),
    )


def aggregate(items: list[TelemetrySpan], *, finalized: bool = True):
    return aggregate_minute(
        SERVICE,
        WINDOW,
        result(items),
        computed_at=WINDOW + timedelta(minutes=2, seconds=30),
        finalized=finalized,
    )


def test_server_only_and_control_routes_are_excluded() -> None:
    items = [
        span(0),
        span(1, kind="CLIENT"),
        span(2, kind="INTERNAL"),
        span(3, route="/health"),
        span(4, route="/__faults/errors"),
        span(5, route="/admin/settings"),
        span(6, route="/administer"),
    ]

    bucket = aggregate(items)

    assert bucket.request_count == 2
    assert bucket.source_count == 2
    assert bucket.quality_status == "insufficient"


def test_error_classification_counts_each_server_request_once() -> None:
    items = [
        span(0, status="ERROR", http_status=500),
        span(1, status="ERROR", http_status=200),
        span(2, status="OK", http_status=503),
        span(3, status="OK", http_status=404),
    ]

    bucket = aggregate(items)

    assert bucket.request_count == 4
    assert bucket.error_count == 3
    assert bucket.error_rate == 0.75


def test_counts_mean_and_p95_are_deterministic() -> None:
    durations = list(range(1, 21))
    bucket = aggregate(
        [span(index, duration_ms=duration) for index, duration in enumerate(durations)]
    )

    assert bucket.request_count == 20
    assert bucket.error_count == 0
    assert bucket.error_rate == 0
    assert bucket.latency_mean_ms == 10.5
    assert bucket.latency_p95_ms == 19
    assert bucket.quality_status == "complete"
    assert bucket.eligible_for_detection is True


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([], None),
        ([7.0], 7.0),
        ([3.0] * 20, 3.0),
        ([1.0] * 19 + [10_000.0], 1.0),
    ],
)
def test_p95_edge_cases(values: list[float], expected: float | None) -> None:
    assert nearest_rank_p95(values) == expected


@pytest.mark.parametrize(
    ("count", "quality", "reason", "eligible"),
    [
        (0, "insufficient", "no_spans", False),
        (1, "insufficient", "low_sample_count", False),
        (19, "insufficient", "low_sample_count", False),
        (20, "complete", None, True),
    ],
)
def test_minimum_sample_boundary(
    count: int,
    quality: str,
    reason: str | None,
    eligible: bool,
) -> None:
    bucket = aggregate([span(index) for index in range(count)])
    assert bucket.quality_status == quality
    assert (reason in bucket.quality_reasons) if reason else bucket.quality_reasons == []
    assert bucket.eligible_for_detection is eligible


def test_missing_status_and_partial_source_block_detection() -> None:
    query = result([span(0, status="UNSET", http_status=None)], partial=True)
    bucket = aggregate_minute(
        SERVICE,
        WINDOW,
        query,
        computed_at=WINDOW + timedelta(minutes=2, seconds=30),
        finalized=True,
    )

    assert bucket.request_count == 0
    assert bucket.invalid_span_count == 1
    assert bucket.quality_status == "partial"
    assert set(bucket.quality_reasons) == {
        "missing_http_status",
        "query_partial",
    }
    assert bucket.eligible_for_detection is False


def test_bucket_id_is_stable_across_replay() -> None:
    first = aggregate([span(index) for index in range(20)])
    second = aggregate([span(index) for index in range(20)])
    assert first.bucket_id == second.bucket_id
    assert first.model_dump() == second.model_dump()


def test_provisional_bucket_is_not_detector_ready() -> None:
    bucket = aggregate([span(index) for index in range(20)], finalized=False)
    assert bucket.quality_status == "complete"
    assert bucket.finalized_at is None
    assert bucket.eligible_for_detection is False


def test_processing_range_advances_without_skipping_long_outage() -> None:
    finalized_through = WINDOW
    boundary = WINDOW + timedelta(hours=9)

    start, end = processing_range(finalized_through, boundary)

    assert start == WINDOW - timedelta(minutes=10)
    assert end == WINDOW + timedelta(minutes=10)


def test_processing_range_replays_overlap_when_caught_up() -> None:
    finalized_through = WINDOW
    boundary = WINDOW + timedelta(minutes=3)

    start, end = processing_range(finalized_through, boundary)

    assert start == WINDOW - timedelta(minutes=10)
    assert end == boundary


def test_processing_range_does_not_move_cursor_past_clock_rollback() -> None:
    boundary = WINDOW
    finalized_through = WINDOW + timedelta(minutes=2)

    start, end = processing_range(finalized_through, boundary)

    assert start == boundary - timedelta(minutes=10)
    assert end == boundary
