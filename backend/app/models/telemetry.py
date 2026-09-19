import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TRACE_ID_PATTERN = r"^[0-9a-f]{32}$"
SPAN_ID_PATTERN = r"^[0-9a-f]{16}$"
SERVICE_ID_PATTERN = r"^svc_[0-9a-f]{64}$"
UTC_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?P<fraction>\.\d{1,9})?(?:Z|\+00:00)$"
)

QueryReason = Literal[
    "duplicate_conflict",
    "invalid_span",
    "query_partial",
    "truncated",
]


def utc_timestamp_to_ns(value: str) -> int:
    match = UTC_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("timestamp must be an RFC3339 UTC value")
    base = datetime.fromisoformat(f"{match.group('date')}T{match.group('time')}+00:00")
    seconds = int(base.timestamp())
    fraction = (match.group("fraction") or "")[1:].ljust(9, "0")
    return seconds * 1_000_000_000 + int(fraction or "0")


def validate_utc_timestamp(value: str) -> str:
    utc_timestamp_to_ns(value)
    return value.replace("+00:00", "Z")


def validate_optional_utc_timestamp(value: str | None) -> str | None:
    return validate_utc_timestamp(value) if value is not None else None


class TelemetryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ServiceReference(TelemetryModel):
    namespace: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
    environment: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")


class TelemetryService(ServiceReference):
    service_id: str = Field(pattern=SERVICE_ID_PATTERN)
    instance_id: str = Field(min_length=1, max_length=128)
    version: str | None = Field(default=None, max_length=128)


class SourceDocument(TelemetryModel):
    index: str = Field(min_length=1, max_length=255)
    document_id: str = Field(min_length=1, max_length=512)


class TelemetryLog(TelemetryModel):
    source: SourceDocument
    service: TelemetryService
    event_time: str
    observed_time: str | None
    severity: Literal["DEBUG", "INFO", "WARN", "ERROR", "FATAL"]
    body: str = Field(max_length=4096)
    trace_id: str | None = Field(default=None, pattern=TRACE_ID_PATTERN)
    span_id: str | None = Field(default=None, pattern=SPAN_ID_PATTERN)
    event: str | None = Field(default=None, max_length=128)
    error_type: str | None = Field(default=None, max_length=128)

    _event_time = field_validator("event_time")(validate_utc_timestamp)
    _observed_time = field_validator("observed_time")(validate_optional_utc_timestamp)


class TelemetrySpan(TelemetryModel):
    source: SourceDocument
    service: TelemetryService
    trace_id: str = Field(pattern=TRACE_ID_PATTERN)
    span_id: str = Field(pattern=SPAN_ID_PATTERN)
    parent_span_id: str | None = Field(default=None, pattern=SPAN_ID_PATTERN)
    name: str = Field(min_length=1, max_length=1024)
    kind: Literal["SERVER", "CLIENT", "INTERNAL", "PRODUCER", "CONSUMER"]
    start_time: str
    end_time: str
    duration_ns: int = Field(ge=0)
    duration_ms: float = Field(ge=0)
    status: Literal["UNSET", "OK", "ERROR"]
    http_method: str | None = Field(default=None, max_length=16)
    http_route: str | None = Field(default=None, max_length=256)
    http_status_code: int | None = Field(default=None, ge=100, le=599)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    _start_time = field_validator("start_time")(validate_utc_timestamp)
    _end_time = field_validator("end_time")(validate_utc_timestamp)

    @model_validator(mode="after")
    def validate_timing(self) -> "TelemetrySpan":
        start_ns = utc_timestamp_to_ns(self.start_time)
        end_ns = utc_timestamp_to_ns(self.end_time)
        if end_ns < start_ns:
            raise ValueError("span end must not precede start")
        if self.duration_ns != end_ns - start_ns:
            raise ValueError("span duration does not match start/end timestamps")
        return self


class NativeHistogram(TelemetryModel):
    count: int = Field(ge=0)
    sum: float | None
    minimum: float | None
    maximum: float | None
    bounds: list[float] = Field(max_length=64)
    counts: list[int] = Field(max_length=65)

    @model_validator(mode="after")
    def validate_buckets(self) -> "NativeHistogram":
        if len(self.counts) != len(self.bounds) + 1:
            raise ValueError("histogram counts must contain one more item than bounds")
        if sum(self.counts) != self.count:
            raise ValueError("histogram bucket counts must sum to count")
        if any(
            right <= left
            for left, right in zip(self.bounds, self.bounds[1:], strict=False)
        ):
            raise ValueError("histogram bounds must be strictly increasing")
        return self


class NativeMetric(TelemetryModel):
    source: SourceDocument
    service: TelemetryService
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    unit: str = Field(max_length=32)
    metric_type: Literal["gauge", "sum", "histogram"]
    temporality: Literal["unspecified", "delta", "cumulative"]
    monotonic: bool | None
    start_time: str | None
    event_time: str
    value: float | None
    histogram: NativeHistogram | None
    labels: dict[str, str] = Field(default_factory=dict)

    _start_time = field_validator("start_time")(validate_optional_utc_timestamp)
    _event_time = field_validator("event_time")(validate_utc_timestamp)

    @model_validator(mode="after")
    def validate_value_shape(self) -> "NativeMetric":
        if self.metric_type == "histogram":
            if self.histogram is None or self.value is not None:
                raise ValueError("histogram metrics require only histogram data")
        elif self.value is None or self.histogram is not None:
            raise ValueError("scalar metrics require only a scalar value")
        return self


class DependencyEdge(TelemetryModel):
    edge_id: str = Field(pattern=r"^edge_[0-9a-f]{64}$")
    source_service: ServiceReference
    target_service: ServiceReference
    window_start: str
    window_end: str
    observed_trace_count: int | None = Field(default=None, ge=1)
    sample_trace_ids: list[str] = Field(max_length=5)
    observed_at: str
    source_kind: Literal["trace_reconstruction", "native_service_map"]

    _window_start = field_validator("window_start")(validate_utc_timestamp)
    _window_end = field_validator("window_end")(validate_utc_timestamp)
    _observed_at = field_validator("observed_at")(validate_utc_timestamp)

    @model_validator(mode="after")
    def validate_window(self) -> "DependencyEdge":
        if utc_timestamp_to_ns(self.window_start) >= utc_timestamp_to_ns(self.window_end):
            raise ValueError("dependency window must be non-empty")
        if self.source_service.namespace != self.target_service.namespace:
            raise ValueError("dependency services must share a namespace")
        if self.source_service.environment != self.target_service.environment:
            raise ValueError("dependency services must share an environment")
        return self


class TelemetryTrace(TelemetryModel):
    trace_id: str = Field(pattern=TRACE_ID_PATTERN)
    spans: list[TelemetrySpan] = Field(min_length=1, max_length=200)
    services: list[ServiceReference] = Field(min_length=1, max_length=20)
    start_time: str
    end_time: str
    root_present: bool
    missing_parent_count: int = Field(ge=0)
    has_error: bool

    _start_time = field_validator("start_time")(validate_utc_timestamp)
    _end_time = field_validator("end_time")(validate_utc_timestamp)


class QueryMetadata(TelemetryModel):
    partial: bool
    truncated: bool
    reasons: list[QueryReason] = Field(max_length=4)
    returned_count: int = Field(ge=0)
    matched_count: int | None = Field(default=None, ge=0)
    malformed_count: int = Field(default=0, ge=0)
    duplicate_count: int = Field(default=0, ge=0)
    duplicate_conflict_count: int = Field(default=0, ge=0)


class TelemetryQueryResult[T](TelemetryModel):
    items: list[T]
    metadata: QueryMetadata
