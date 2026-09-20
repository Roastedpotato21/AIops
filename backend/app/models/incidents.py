from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.models.detection import (
    DOMAIN_ID_PATTERN,
    VERSION_PATTERN,
    Failure,
    FeatureName,
    NormalizedAnomaly,
    ServiceKey,
    ServiceMetricBucket,
    TimeRange,
)
from app.models.telemetry import (
    DependencyEdge,
    TelemetryModel,
    validate_optional_utc_timestamp,
    validate_utc_timestamp,
)

IncidentState = Literal["open", "recovering", "resolved"]
IncidentSeverity = Literal["low", "medium", "high", "critical"]
EvidenceStatus = Literal["pending", "ready", "partial", "failed"]
ReasonCode = Literal[
    "low_sample_count",
    "no_spans",
    "sampling_enabled",
    "pipeline_stale",
    "query_partial",
    "invalid_span",
    "late_data",
    "duplicate_conflict",
    "missing_http_status",
    "source_expired",
    "truncated",
    "clock_skew",
    "detector_unready",
    "baseline_missing",
    "tool_failure",
    "budget_exhausted",
    "unobserved_service",
    "redaction_applied",
]


class RecoveryBaseline(TelemetryModel):
    window: TimeRange
    bucket_ids: list[str] = Field(min_length=10, max_length=30)
    latency_p95_median_ms: float = Field(ge=0, allow_inf_nan=False)
    error_rate_median: float = Field(ge=0, le=1, allow_inf_nan=False)
    captured_at: str

    _captured_at = field_validator("captured_at")(validate_utc_timestamp)


class RelatedIncident(TelemetryModel):
    incident_id: str = Field(pattern=r"^incident_[0-9a-f]{64}$")
    reason: Literal["shared_trace", "dependency_and_overlap", "same_service_overlap"]
    evidence_ids: list[str] = Field(min_length=1, max_length=8)
    linked_at: str

    _linked_at = field_validator("linked_at")(validate_utc_timestamp)


class SchedulingReservation(TelemetryModel):
    investigation_id: str = Field(pattern=r"^inv_[0-9a-f]{64}$")
    trigger: Literal["automatic", "user"]
    principal_id: str = Field(min_length=1, max_length=128)
    idempotency_key_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_evidence_version: int | None = Field(default=None, ge=1)
    resolved_evidence_bundle_id: str = Field(pattern=r"^bundle_[0-9a-f]{64}$")
    resolved_evidence_version: int = Field(ge=1)
    reserved_at: str
    provider_id: str = Field(min_length=1, max_length=63)
    model_id: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(pattern=VERSION_PATTERN)
    tool_contract_version: str = Field(pattern=VERSION_PATTERN)

    _reserved_at = field_validator("reserved_at")(validate_utc_timestamp)


class Incident(TelemetryModel):
    schema_version: str = Field(default="1.0.0", pattern=VERSION_PATTERN)
    incident_id: str = Field(pattern=r"^incident_[0-9a-f]{64}$")
    primary_service: ServiceKey
    affected_services: list[ServiceKey] = Field(min_length=1, max_length=20)
    feature: FeatureName
    state: IncidentState
    severity: IncidentSeverity
    peak_severity: IncidentSeverity
    severity_reason: str = Field(min_length=1, max_length=512)
    severity_bucket_ids: list[str] = Field(max_length=5)
    opened_by_anomaly_id: str = Field(pattern=r"^anomaly_[0-9a-f]{64}$")
    anomaly_count: int = Field(ge=1)
    recent_anomaly_ids: list[str] = Field(min_length=1, max_length=100)
    related_incidents: list[RelatedIncident] = Field(max_length=20)
    first_affected_at: str
    last_affected_at: str
    detected_at: str
    updated_at: str
    recovering_since: str | None = None
    resolved_at: str | None = None
    recovery_baseline: RecoveryBaseline | None = None
    healthy_bucket_streak: int = Field(default=0, ge=0)
    last_recovery_bucket_end: str | None = None
    suspected_root_service: ServiceKey | None = None
    suspected_root_evidence_ids: list[str] = Field(default_factory=list, max_length=8)
    latest_evidence_bundle_id: str | None = Field(default=None, pattern=r"^bundle_[0-9a-f]{64}$")
    evidence_version: int = Field(default=0, ge=0)
    evidence_status: EvidenceStatus = "pending"
    latest_investigation_id: str | None = Field(default=None, pattern=r"^inv_[0-9a-f]{64}$")
    scheduling_reservation: SchedulingReservation | None = None
    automatic_job_count: int = Field(default=0, ge=0, le=5)
    user_job_count: int = Field(default=0, ge=0, le=5)
    last_automatic_job_at: str | None = None
    last_user_job_at: str | None = None
    last_evidence_refresh_at: str | None = None
    resolution_bucket_end: str | None = None
    policy_version: str = Field(default="1.0.0", pattern=VERSION_PATTERN)
    fixture_source: bool = False

    _first = field_validator("first_affected_at")(validate_utc_timestamp)
    _last = field_validator("last_affected_at")(validate_utc_timestamp)
    _detected = field_validator("detected_at")(validate_utc_timestamp)
    _updated = field_validator("updated_at")(validate_utc_timestamp)
    _recovering = field_validator("recovering_since")(validate_optional_utc_timestamp)
    _resolved = field_validator("resolved_at")(validate_optional_utc_timestamp)
    _recovery_end = field_validator("last_recovery_bucket_end")(validate_optional_utc_timestamp)
    _last_automatic = field_validator("last_automatic_job_at")(validate_optional_utc_timestamp)
    _last_user = field_validator("last_user_job_at")(validate_optional_utc_timestamp)
    _last_refresh = field_validator("last_evidence_refresh_at")(validate_optional_utc_timestamp)
    _resolution_end = field_validator("resolution_bucket_end")(validate_optional_utc_timestamp)

    @model_validator(mode="after")
    def validate_identity(self) -> "Incident":
        if self.primary_service not in self.affected_services:
            raise ValueError("primary service must be affected")
        if len({item.service_id for item in self.affected_services}) != len(self.affected_services):
            raise ValueError("affected services must be unique")
        if len(set(self.recent_anomaly_ids)) != len(self.recent_anomaly_ids):
            raise ValueError("recent anomaly IDs must be unique")
        if self.suspected_root_service is None and self.suspected_root_evidence_ids:
            raise ValueError("root evidence requires a suspected root service")
        return self


class QueryParameters(TelemetryModel):
    service_ids: list[str] = Field(min_length=1, max_length=20)
    window: TimeRange
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    severity_min: Literal["DEBUG", "INFO", "WARN", "ERROR", "FATAL"] | None = None
    feature: FeatureName | None = None
    features: list[FeatureName] = Field(default_factory=list, max_length=2)
    incident_id: str | None = Field(default=None, pattern=r"^incident_[0-9a-f]{64}$")
    bundle_id: str | None = Field(default=None, pattern=r"^bundle_[0-9a-f]{64}$")
    detector_id: str | None = Field(default=None, min_length=1, max_length=256)
    document_id: str | None = Field(default=None, min_length=1, max_length=512)
    max_spans: int | None = Field(default=None, ge=1, le=200)
    text_contains: str | None = Field(default=None, max_length=256)
    status: Literal["error", "ok"] | None = None
    min_duration_ms: float | None = Field(default=None, ge=0)
    limit: int = Field(ge=1, le=200)
    direction: Literal["upstream", "downstream", "both"] | None = None
    include_native: bool = False
    cursor_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class Provenance(TelemetryModel):
    query_id: str = Field(pattern=r"^query_[0-9a-f]{64}$")
    template_id: str = Field(min_length=1, max_length=128)
    template_version: str = Field(pattern=VERSION_PATTERN)
    parameters: QueryParameters
    retrieved_at: str
    source_cutoff: str
    returned_count: int = Field(ge=0)
    matched_count: int | None = Field(default=None, ge=0)
    truncated: bool

    _retrieved = field_validator("retrieved_at")(validate_utc_timestamp)
    _cutoff = field_validator("source_cutoff")(validate_utc_timestamp)


class DocumentLocator(TelemetryModel):
    kind: Literal["document"] = "document"
    index: str = Field(min_length=1, max_length=255)
    document_id: str = Field(min_length=1, max_length=512)
    source_version: str | None = Field(default=None, max_length=128)


class QueryLocator(TelemetryModel):
    kind: Literal["query"] = "query"
    query_id: str = Field(pattern=r"^query_[0-9a-f]{64}$")
    index_alias: str = Field(min_length=1, max_length=255)


class TraceLocator(TelemetryModel):
    kind: Literal["trace"] = "trace"
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    index_alias: str = Field(min_length=1, max_length=255)


SourceLocator = DocumentLocator | QueryLocator | TraceLocator


class AnomalySnapshot(TelemetryModel):
    kind: Literal["anomaly_result"] = "anomaly_result"
    anomaly: NormalizedAnomaly


class MetricBucketSnapshot(TelemetryModel):
    kind: Literal["metric_bucket"] = "metric_bucket"
    bucket: ServiceMetricBucket


class LogSnapshot(TelemetryModel):
    kind: Literal["log_record"] = "log_record"
    event_time: str
    severity: Literal["DEBUG", "INFO", "WARN", "ERROR", "FATAL"]
    body: str = Field(max_length=4096)
    service: ServiceKey
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    span_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    error_type: str | None = Field(default=None, max_length=128)

    _event_time = field_validator("event_time")(validate_utc_timestamp)


class SpanSnapshot(TelemetryModel):
    kind: Literal["span"] = "span"
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    span_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    parent_span_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    service: ServiceKey
    name: str = Field(min_length=1, max_length=256)
    span_kind: Literal["SERVER", "CLIENT", "INTERNAL", "PRODUCER", "CONSUMER"]
    start_time: str
    end_time: str
    duration_ms: float = Field(ge=0)
    status: Literal["UNSET", "OK", "ERROR"]
    http_status_code: int | None = Field(default=None, ge=100, le=599)
    http_route: str | None = Field(default=None, max_length=256)

    _start = field_validator("start_time")(validate_utc_timestamp)
    _end = field_validator("end_time")(validate_utc_timestamp)


class TraceSnapshot(TelemetryModel):
    kind: Literal["trace"] = "trace"
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    window: TimeRange
    services: list[ServiceKey] = Field(min_length=1, max_length=20)
    spans: list[SpanSnapshot] = Field(min_length=1, max_length=200)
    root_present: bool
    truncated: bool
    missing_parent_count: int = Field(ge=0)
    observed_span_count: int | None = Field(default=None, ge=0)


class DependencySnapshot(TelemetryModel):
    kind: Literal["dependency_edge"] = "dependency_edge"
    edge: DependencyEdge


EvidenceSnapshot = (
    AnomalySnapshot
    | MetricBucketSnapshot
    | LogSnapshot
    | SpanSnapshot
    | TraceSnapshot
    | DependencySnapshot
)


class EvidenceItem(TelemetryModel):
    schema_version: str = Field(default="1.0.0", pattern=VERSION_PATTERN)
    record_kind: Literal["evidence_item"] = "evidence_item"
    owner_incident_id: str = Field(pattern=r"^incident_[0-9a-f]{64}$")
    evidence_id: str = Field(pattern=r"^ev_[0-9a-f]{64}$")
    evidence_type: Literal[
        "anomaly_result", "metric_bucket", "log_record", "span", "trace", "dependency_edge"
    ]
    source: SourceLocator
    service: ServiceKey
    window: TimeRange
    summary: str = Field(min_length=1, max_length=512)
    quality_status: Literal["complete", "partial", "insufficient", "unknown"]
    quality_reasons: list[ReasonCode] = Field(max_length=16)
    redaction_status: Literal["checked_clear", "redacted"]
    redaction_version: str = Field(pattern=VERSION_PATTERN)
    provenance: Provenance
    snapshot: EvidenceSnapshot
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stored_bytes: int = Field(ge=1, le=262_144)
    created_at: str

    _created = field_validator("created_at")(validate_utc_timestamp)

    @model_validator(mode="after")
    def validate_kind(self) -> "EvidenceItem":
        if self.evidence_type != self.snapshot.kind:
            raise ValueError("evidence type must match snapshot kind")
        return self


class EvidenceBundle(TelemetryModel):
    schema_version: str = Field(default="1.0.0", pattern=VERSION_PATTERN)
    record_kind: Literal["evidence_bundle"] = "evidence_bundle"
    owner_incident_id: str = Field(pattern=r"^incident_[0-9a-f]{64}$")
    bundle_id: str = Field(pattern=r"^bundle_[0-9a-f]{64}$")
    incident_id: str = Field(pattern=r"^incident_[0-9a-f]{64}$")
    version: int = Field(ge=1)
    window: TimeRange
    evidence_ids: list[str] = Field(min_length=1, max_length=300)
    quality_status: Literal["complete", "partial", "insufficient", "unknown"]
    quality_reasons: list[ReasonCode] = Field(max_length=16)
    total_bytes: int = Field(ge=1, le=2_097_152)
    created_at: str

    _created = field_validator("created_at")(validate_utc_timestamp)

    @model_validator(mode="after")
    def validate_ids(self) -> "EvidenceBundle":
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence IDs must be unique")
        if self.owner_incident_id != self.incident_id:
            raise ValueError("bundle owner must be its incident")
        return self


class TimelineEntry(TelemetryModel):
    entry_id: str = Field(pattern=r"^timeline_[0-9a-f]{64}$")
    occurred_at: str
    kind: Literal["detected", "anomaly", "evidence", "investigation", "recovering", "resolved"]
    summary: str = Field(min_length=1, max_length=512)
    evidence_ids: list[str] = Field(max_length=8)
    related_investigation_id: str | None = Field(default=None, pattern=r"^inv_[0-9a-f]{64}$")

    _occurred = field_validator("occurred_at")(validate_utc_timestamp)


class IncidentSummary(TelemetryModel):
    incident_id: str = Field(pattern=r"^incident_[0-9a-f]{64}$")
    primary_service: ServiceKey
    feature: FeatureName
    state: IncidentState
    severity: IncidentSeverity
    peak_severity: IncidentSeverity
    detected_at: str
    first_affected_at: str
    updated_at: str
    evidence_status: EvidenceStatus
    latest_investigation_id: str | None = None
    fixture_source: bool = False


class Page[T](TelemetryModel):
    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False


class IncidentDetail(TelemetryModel):
    incident: Incident
    evidence_bundle: EvidenceBundle | None
    timeline: Page[TimelineEntry]
    latest_investigation: None = None


class EvidenceResponse(TelemetryModel):
    incident_id: str = Field(pattern=r"^incident_[0-9a-f]{64}$")
    bundle: EvidenceBundle
    items: Page[EvidenceItem]


class Freshness(TelemetryModel):
    generated_at: str
    latest_source_at: str | None = None
    age_seconds: float | None = Field(default=None, ge=0)
    state: Literal["fresh", "stale", "unknown", "not_applicable"]

    _generated = field_validator("generated_at")(validate_utc_timestamp)
    _latest = field_validator("latest_source_at")(validate_optional_utc_timestamp)


class Coverage(TelemetryModel):
    status: Literal["complete", "partial", "unknown"]
    reasons: list[ReasonCode] = Field(max_length=16)
    omitted_count: int | None = Field(default=None, ge=0)
    message: str | None = Field(default=None, max_length=512)


class ApiResponse[T](TelemetryModel):
    result: T
    request_id: str
    freshness: Freshness
    coverage: Coverage


class IncidentWorkerCursor(TelemetryModel):
    kind: Literal["incident"] = "incident"
    execution_ended_at: str
    anomaly_id: str = Field(pattern=r"^anomaly_[0-9a-f]{64}$")

    _execution = field_validator("execution_ended_at")(validate_utc_timestamp)


class IncidentWorkerState(TelemetryModel):
    schema_version: str = Field(default="1.0.0", pattern=VERSION_PATTERN)
    record_kind: Literal["worker_cursor"] = "worker_cursor"
    worker_state_id: str = Field(pattern=DOMAIN_ID_PATTERN)
    role: Literal["incident"] = "incident"
    partition: str = Field(min_length=1, max_length=128)
    cursor: IncidentWorkerCursor
    owner_id: str = Field(min_length=1, max_length=128)
    heartbeat_at: str
    status: Literal["starting", "running", "degraded", "stopped"]
    last_error: Failure | None = None
    updated_at: str

    _heartbeat = field_validator("heartbeat_at")(validate_utc_timestamp)
    _updated = field_validator("updated_at")(validate_utc_timestamp)
