"""Typed development-only fixture construction for explicit validation runs."""

from datetime import UTC, datetime

from app.models.detection import NormalizedAnomaly, ServiceMetricBucket, deterministic_id
from app.models.telemetry import SourceDocument

FIXTURE_SOURCE_INDEX = "phase6-development-fixture"


def build_fixture(bucket: ServiceMetricBucket, *, observed_at: datetime) -> NormalizedAnomaly:
    if not (
        bucket.service.name == "payment-service"
        and bucket.eligible_for_detection
        and bucket.quality_status == "complete"
        and bucket.finalized_at is not None
        and bucket.late_span_count == 0
        and bucket.latency_p95_ms is not None
    ):
        raise ValueError("fixture requires a detector-ready payment latency bucket")
    source_id = f"phase9-development:{bucket.bucket_id}:latency_p95_ms"
    timestamp = observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return NormalizedAnomaly(
        schema_version="1.0.0",
        anomaly_id=deterministic_id("anomaly", [FIXTURE_SOURCE_INDEX, source_id]),
        detector_id="phase9-development-fixture-latency",
        detector_name="phase9-development-fixture-latency",
        detector_config_version="1.0.0",
        service=bucket.service,
        feature="latency_p95_ms",
        feature_value=bucket.latency_p95_ms,
        input_bucket_id=bucket.bucket_id,
        detector_window=bucket.window,
        affected_window=bucket.window,
        execution_started_at=timestamp,
        execution_ended_at=timestamp,
        anomaly_grade=0.8,
        detector_confidence=0.9,
        result_status="anomalous",
        error_reason=None,
        source=SourceDocument(index=FIXTURE_SOURCE_INDEX, document_id=source_id),
        observed_at=timestamp,
    )
