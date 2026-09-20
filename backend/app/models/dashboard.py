from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.models.detection import (
    DetectorStatus,
    FeatureName,
    ServiceKey,
    ServiceMetricBucket,
    TimeRange,
)
from app.models.incidents import IncidentSummary, Page, ReasonCode, TraceSnapshot
from app.models.telemetry import (
    DependencyEdge,
    TelemetryModel,
    utc_timestamp_to_ns,
    validate_utc_timestamp,
)


class ServiceHealth(TelemetryModel):
    service: ServiceKey
    state: Literal["healthy", "degraded", "unhealthy", "unknown"]
    reason: str = Field(min_length=1, max_length=512)
    assessed_at: str
    latest_bucket_end: str | None
    telemetry_age_seconds: float | None = Field(default=None, ge=0)
    active_incident_ids: list[str] = Field(max_length=100)
    quality_status: Literal["complete", "partial", "insufficient", "unknown"]
    quality_reasons: list[ReasonCode] = Field(max_length=16)


class ServiceSummary(TelemetryModel):
    service: ServiceKey
    health: ServiceHealth
    last_seen_at: str | None
    active_incident_count: int = Field(ge=0)


class ServiceInstance(TelemetryModel):
    instance_record_id: str = Field(pattern=r"^inst_[0-9a-f]{64}$")
    service: ServiceKey
    instance_id: str = Field(min_length=1, max_length=128)
    service_version: str | None = Field(default=None, min_length=1, max_length=128)
    first_seen_at: str
    last_seen_at: str
    last_ingested_at: str

    _first_seen_at = field_validator("first_seen_at")(validate_utc_timestamp)
    _last_seen_at = field_validator("last_seen_at")(validate_utc_timestamp)
    _last_ingested_at = field_validator("last_ingested_at")(validate_utc_timestamp)

    @model_validator(mode="after")
    def validate_seen_range(self) -> "ServiceInstance":
        if utc_timestamp_to_ns(self.last_seen_at) < utc_timestamp_to_ns(self.first_seen_at):
            raise ValueError("last_seen_at must not precede first_seen_at")
        return self


class ServiceDetail(TelemetryModel):
    summary: ServiceSummary
    instances: list[ServiceInstance] = Field(max_length=100)
    detectors: list[DetectorStatus] = Field(max_length=2)
    latest_bucket: ServiceMetricBucket | None
    dependency_count: int | None = Field(default=None, ge=0)


class ServiceCounts(TelemetryModel):
    healthy: int = Field(ge=0)
    degraded: int = Field(ge=0)
    unhealthy: int = Field(ge=0)
    unknown: int = Field(ge=0)


class ComponentStatus(TelemetryModel):
    name: Literal[
        "collector",
        "data_prepper",
        "opensearch",
        "aggregation",
        "incident",
        "investigation",
        "detectors",
    ]
    state: Literal["healthy", "degraded", "unavailable", "unknown"]
    checked_at: str
    reason: str | None = Field(default=None, max_length=256)


class Overview(TelemetryModel):
    overall_health: Literal["healthy", "degraded", "unhealthy", "unknown"]
    service_counts: ServiceCounts
    active_incident_count: int = Field(ge=0)
    recent_incidents: list[IncidentSummary] = Field(max_length=10)
    components: list[ComponentStatus] = Field(max_length=10)


class MetricLabel(TelemetryModel):
    key: str = Field(min_length=1, max_length=64)
    value: str = Field(max_length=128)


class NativeScalarValue(TelemetryModel):
    kind: Literal["scalar"] = "scalar"
    value: float = Field(allow_inf_nan=False)


class NativeHistogramValue(TelemetryModel):
    kind: Literal["histogram"] = "histogram"
    count: int = Field(ge=0)
    sum: float | None = Field(allow_inf_nan=False)
    bounds: list[float] = Field(max_length=64)
    counts: list[int] = Field(max_length=65)

    @model_validator(mode="after")
    def validate_histogram(self) -> "NativeHistogramValue":
        if len(self.counts) != len(self.bounds) + 1 or sum(self.counts) != self.count:
            raise ValueError("invalid histogram bucket counts")
        if any(right <= left for left, right in zip(self.bounds, self.bounds[1:], strict=False)):
            raise ValueError("histogram bounds must be strictly increasing")
        return self


class NativeMetricSnapshot(TelemetryModel):
    kind: Literal["native_metric"] = "native_metric"
    service: ServiceKey
    name: str = Field(min_length=1, max_length=128)
    unit: str = Field(max_length=32)
    window: TimeRange
    metric_type: Literal["gauge", "sum", "histogram"]
    temporality: Literal["unspecified", "delta", "cumulative"]
    attribute_labels: list[MetricLabel] = Field(default_factory=list, max_length=16)
    value: NativeScalarValue | NativeHistogramValue | None


class MetricsResponse(TelemetryModel):
    service: ServiceKey
    window: TimeRange
    interval_seconds: Literal[60] = 60
    requested_features: list[FeatureName] = Field(min_length=1, max_length=2)
    buckets: Page[ServiceMetricBucket]
    native_points: list[NativeMetricSnapshot] = Field(max_length=20)


class DependenciesResponse(TelemetryModel):
    service: ServiceKey
    window: TimeRange
    edges: Page[DependencyEdge]


class TraceResponse(TelemetryModel):
    trace: TraceSnapshot
    evidence_id: str | None = Field(default=None, pattern=r"^ev_[0-9a-f]{64}$")
    out_of_scope_span_count: int = Field(ge=0)
