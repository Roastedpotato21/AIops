import hashlib
import json
import math
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.models.telemetry import (
    SERVICE_ID_PATTERN,
    SourceDocument,
    TelemetryModel,
    utc_timestamp_to_ns,
    validate_optional_utc_timestamp,
    validate_utc_timestamp,
)

VERSION_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+$"
DOMAIN_ID_PATTERN = r"^[a-z]+_[0-9a-f]{64}$"


def deterministic_id(prefix: str, parts: list[str | int]) -> str:
    payload = json.dumps(parts, ensure_ascii=True, separators=(",", ":")).encode()
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()}"


class ServiceKey(TelemetryModel):
    service_id: str = Field(pattern=SERVICE_ID_PATTERN)
    namespace: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
    environment: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")

    @model_validator(mode="after")
    def validate_service_id(self) -> "ServiceKey":
        expected = deterministic_id(
            "svc",
            [self.namespace, self.environment, self.name],
        )
        if self.service_id != expected:
            raise ValueError("service_id does not match service identity")
        return self


class TimeRange(TelemetryModel):
    start: str
    end: str

    _start = field_validator("start")(validate_utc_timestamp)
    _end = field_validator("end")(validate_utc_timestamp)

    @model_validator(mode="after")
    def validate_range(self) -> "TimeRange":
        if utc_timestamp_to_ns(self.start) >= utc_timestamp_to_ns(self.end):
            raise ValueError("time range must be non-empty")
        return self


QualityStatus = Literal["complete", "partial", "insufficient", "unknown"]
QualityReason = Literal[
    "low_sample_count",
    "no_spans",
    "sampling_enabled",
    "pipeline_stale",
    "query_partial",
    "invalid_span",
    "late_data",
    "duplicate_conflict",
    "missing_http_status",
    "truncated",
    "clock_skew",
]
FeatureName = Literal["latency_p95_ms", "error_rate"]


class Failure(TelemetryModel):
    code: Literal[
        "timeout",
        "unavailable",
        "rate_limited",
        "invalid_output",
        "invalid_citation",
        "forbidden",
        "not_found",
        "invalid_argument",
        "source_expired",
        "budget_exhausted",
        "storage_error",
        "unsupported_metric",
    ]
    message: str = Field(min_length=1, max_length=512)
    retryable: bool


class ServiceMetricBucket(TelemetryModel):
    schema_version: str = Field(pattern=VERSION_PATTERN)
    bucket_id: str = Field(pattern=r"^bucket_[0-9a-f]{64}$")
    service: ServiceKey
    window: TimeRange
    bucket_time: str
    request_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    error_rate: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    latency_mean_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    latency_p95_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    source_count: int = Field(ge=0)
    invalid_span_count: int = Field(ge=0)
    late_span_count: int = Field(ge=0)
    quality_status: QualityStatus
    quality_reasons: list[QualityReason] = Field(max_length=16)
    eligible_for_detection: bool
    source_kind: Literal["server_spans"]
    aggregation_version: str = Field(pattern=VERSION_PATTERN)
    sampling_fraction: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    computed_at: str
    finalized_at: str | None
    source_visible_through: str

    _bucket_time = field_validator("bucket_time")(validate_utc_timestamp)
    _computed_at = field_validator("computed_at")(validate_utc_timestamp)
    _finalized_at = field_validator("finalized_at")(validate_optional_utc_timestamp)
    _source_visible = field_validator("source_visible_through")(validate_utc_timestamp)

    @model_validator(mode="after")
    def validate_bucket(self) -> "ServiceMetricBucket":
        start_ns = utc_timestamp_to_ns(self.window.start)
        end_ns = utc_timestamp_to_ns(self.window.end)
        if end_ns - start_ns != 60_000_000_000 or start_ns % 60_000_000_000:
            raise ValueError("metric window must be one UTC-aligned minute")
        if self.bucket_time != self.window.start:
            raise ValueError("bucket_time must equal window start")
        expected = deterministic_id(
            "bucket",
            [self.service.service_id, str(start_ns), self.aggregation_version],
        )
        if self.bucket_id != expected:
            raise ValueError("bucket_id does not match service/window/version")
        if self.error_count > self.request_count or self.source_count != self.request_count:
            raise ValueError("bucket counts are inconsistent")
        if self.request_count == 0 and any(
            value is not None
            for value in (self.error_rate, self.latency_mean_ms, self.latency_p95_ms)
        ):
            raise ValueError("empty buckets cannot contain calculated values")
        if self.request_count and any(
            value is None
            for value in (self.error_rate, self.latency_mean_ms, self.latency_p95_ms)
        ):
            raise ValueError("non-empty buckets require calculated values")
        if len(set(self.quality_reasons)) != len(self.quality_reasons):
            raise ValueError("quality reasons must be unique")
        if self.eligible_for_detection and (
            self.finalized_at is None or self.request_count < 20
        ):
            raise ValueError("detector eligibility requires finalized complete data")
        return self


class DetectorRegistration(TelemetryModel):
    schema_version: str = Field(pattern=VERSION_PATTERN)
    record_kind: Literal["detector_registration"]
    registration_id: str = Field(pattern=r"^detreg_[0-9a-f]{64}$")
    service: ServiceKey
    feature: FeatureName
    native_detector_id: str | None = Field(default=None, max_length=256)
    detector_name: str = Field(min_length=1, max_length=256)
    config_version: str = Field(pattern=VERSION_PATTERN)
    aggregation_version: str = Field(pattern=VERSION_PATTERN)
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["planned", "active", "retired", "failed"]
    activated_at: str | None
    retired_at: str | None
    updated_at: str
    last_error: Failure | None = None

    _activated = field_validator("activated_at")(validate_optional_utc_timestamp)
    _retired = field_validator("retired_at")(validate_optional_utc_timestamp)
    _updated = field_validator("updated_at")(validate_utc_timestamp)


class AggregationCursor(TelemetryModel):
    kind: Literal["aggregation"]
    service_id: str = Field(pattern=SERVICE_ID_PATTERN)
    finalized_through: str
    aggregation_version: str = Field(pattern=VERSION_PATTERN)

    _finalized_through = field_validator("finalized_through")(validate_utc_timestamp)


class AggregationWorkerState(TelemetryModel):
    schema_version: str = Field(pattern=VERSION_PATTERN)
    record_kind: Literal["worker_cursor"]
    worker_state_id: str = Field(pattern=r"^worker_[0-9a-f]{64}$")
    role: Literal["aggregation"]
    partition: str = Field(min_length=1, max_length=128)
    cursor: AggregationCursor
    owner_id: str = Field(min_length=1, max_length=128)
    heartbeat_at: str
    status: Literal["starting", "running", "degraded", "stopped"]
    last_error: Failure | None = None
    updated_at: str

    _heartbeat = field_validator("heartbeat_at")(validate_utc_timestamp)
    _updated_at = field_validator("updated_at")(validate_utc_timestamp)


class DetectorStatus(TelemetryModel):
    detector_id: str = Field(min_length=1, max_length=256)
    detector_name: str = Field(min_length=1, max_length=256)
    service: ServiceKey
    feature: FeatureName
    config_version: str = Field(pattern=VERSION_PATTERN)
    state: Literal[
        "not_started",
        "warming_up",
        "ready",
        "insufficient_data",
        "failed",
        "stopped",
    ]
    checked_at: str
    last_result_at: str | None
    reason: str | None = Field(default=None, max_length=512)

    _checked = field_validator("checked_at")(validate_utc_timestamp)
    _last_result = field_validator("last_result_at")(validate_optional_utc_timestamp)


class AnomalyProcessing(TelemetryModel):
    processing_state: Literal["pending", "assigned", "processed", "failed"] = "pending"
    disposition: Literal[
        "undecided",
        "non_anomalous",
        "opened",
        "attached",
        "suppressed_quality",
        "historical_unassigned",
    ] = "undecided"
    decision_reason: str | None = Field(default=None, max_length=512)
    incident_id: str | None = Field(default=None, pattern=r"^incident_[0-9a-f]{64}$")
    policy_version: str = Field(default="1.0.0", pattern=VERSION_PATTERN)
    processed_at: str | None = None
    last_error: Failure | None = None

    _processed_at = field_validator("processed_at")(validate_optional_utc_timestamp)


class NormalizedAnomaly(TelemetryModel):
    schema_version: str = Field(pattern=VERSION_PATTERN)
    anomaly_id: str = Field(pattern=r"^anomaly_[0-9a-f]{64}$")
    detector_id: str = Field(min_length=1, max_length=256)
    detector_name: str = Field(min_length=1, max_length=256)
    detector_config_version: str = Field(pattern=VERSION_PATTERN)
    service: ServiceKey
    feature: FeatureName
    feature_value: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    input_bucket_id: str | None = Field(default=None, pattern=r"^bucket_[0-9a-f]{64}$")
    detector_window: TimeRange
    affected_window: TimeRange | None
    execution_started_at: str
    execution_ended_at: str
    anomaly_grade: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    detector_confidence: float | None = Field(
        default=None,
        ge=0,
        le=1,
        allow_inf_nan=False,
    )
    result_status: Literal["anomalous", "normal", "insufficient_data", "failed"]
    error_reason: str | None = Field(default=None, max_length=512)
    source: SourceDocument
    observed_at: str
    processing: AnomalyProcessing = Field(default_factory=AnomalyProcessing)

    _execution_started = field_validator("execution_started_at")(validate_utc_timestamp)
    _execution_ended = field_validator("execution_ended_at")(validate_utc_timestamp)
    _observed = field_validator("observed_at")(validate_utc_timestamp)

    @model_validator(mode="after")
    def validate_result(self) -> "NormalizedAnomaly":
        if self.feature == "error_rate" and self.feature_value is not None:
            if not math.isfinite(self.feature_value) or self.feature_value > 1:
                raise ValueError("error-rate feature must be a ratio")
        expected = deterministic_id(
            "anomaly",
            [self.source.index, self.source.document_id],
        )
        if self.anomaly_id != expected:
            raise ValueError("anomaly_id does not match native source")
        return self
