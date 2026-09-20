from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator

from app.models.detection import Failure, FeatureName, ServiceKey, TimeRange
from app.models.incidents import EvidenceBundle, EvidenceItem, Incident, Provenance
from app.models.telemetry import (
    TelemetryModel,
    validate_optional_utc_timestamp,
    validate_utc_timestamp,
)

ToolName = Literal[
    "get_incident",
    "search_logs",
    "search_traces",
    "get_trace",
    "get_metrics",
    "get_service_dependencies",
    "find_related_errors",
]
ToolStatus = Literal["ok", "empty", "partial", "error"]


class SharedQueryParams(TelemetryModel):
    service_ids: list[str] = Field(min_length=1, max_length=5)
    window: TimeRange
    cursor: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def unique_services(self) -> "SharedQueryParams":
        if len(set(self.service_ids)) != len(self.service_ids):
            raise ValueError("service IDs must be unique")
        return self


class GetIncidentParams(TelemetryModel):
    incident_id: str = Field(pattern=r"^incident_[0-9a-f]{64}$")


class SearchLogsParams(SharedQueryParams):
    severity_min: Literal["DEBUG", "INFO", "WARN", "ERROR", "FATAL"] = "ERROR"
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    text_contains: str | None = Field(default=None, max_length=256)
    limit: int = Field(default=20, ge=1, le=50)


class SearchTracesParams(SharedQueryParams):
    status: Literal["error", "ok"] | None = None
    min_duration_ms: float | None = Field(default=None, ge=0)
    limit: int = Field(default=10, ge=1, le=20)


class GetTraceParams(TelemetryModel):
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    max_spans: int = Field(default=100, ge=1, le=200)


class MetricsParams(SharedQueryParams):
    features: list[FeatureName] = Field(
        default_factory=lambda: ["latency_p95_ms", "error_rate"], min_length=1, max_length=2
    )
    include_native: bool = False
    limit: int = Field(default=60, ge=1, le=100)


class DependenciesParams(TelemetryModel):
    service_id: str = Field(pattern=r"^svc_[0-9a-f]{64}$")
    window: TimeRange
    direction: Literal["upstream", "downstream", "both"] = "both"
    limit: int = Field(default=20, ge=1, le=20)
    cursor: str | None = Field(default=None, max_length=2048)


class RelatedErrorsParams(SharedQueryParams):
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    limit: int = Field(default=5, ge=1, le=10)


ToolArguments = (
    GetIncidentParams
    | SearchLogsParams
    | SearchTracesParams
    | GetTraceParams
    | MetricsParams
    | DependenciesParams
    | RelatedErrorsParams
)


class ToolCall(TelemetryModel):
    call_id: UUID
    name: ToolName
    arguments: ToolArguments

    @model_validator(mode="after")
    def arguments_match_name(self) -> "ToolCall":
        expected = {
            "get_incident": GetIncidentParams,
            "search_logs": SearchLogsParams,
            "search_traces": SearchTracesParams,
            "get_trace": GetTraceParams,
            "get_metrics": MetricsParams,
            "get_service_dependencies": DependenciesParams,
            "find_related_errors": RelatedErrorsParams,
        }[self.name]
        if not isinstance(self.arguments, expected):
            raise ValueError("tool arguments do not match registered tool")
        return self


class ToolContext(TelemetryModel):
    principal_id: str = Field(min_length=1, max_length=128)
    job_id: str = Field(pattern=r"^inv_[0-9a-f]{64}$")
    incident_id: str = Field(pattern=r"^incident_[0-9a-f]{64}$")
    allowed_service_ids: list[str] = Field(min_length=1, max_length=20)
    allowed_window: TimeRange
    deadline_at: str
    evidence_allowlist: list[str] = Field(max_length=400)

    _deadline = field_validator("deadline_at")(validate_utc_timestamp)


class InvestigationBudget(TelemetryModel):
    max_tool_calls: int = Field(default=8, ge=1, le=8)
    max_provider_rounds: int = Field(default=6, ge=1, le=6)
    max_input_tokens: int = Field(default=24_000, ge=1, le=24_000)
    max_output_tokens: int = Field(default=4_000, ge=1, le=4_000)
    max_duration_seconds: int = Field(default=60, ge=1, le=60)
    max_cost_usd: float | None = Field(default=None, gt=0)
    max_additional_evidence_bytes: int = Field(default=1_048_576, ge=1, le=1_048_576)


class IncidentToolView(TelemetryModel):
    incident: Incident
    bundle: EvidenceBundle
    evidence_ids: list[str] = Field(max_length=300)


class LogResults(TelemetryModel):
    items: list[EvidenceItem] = Field(max_length=50)


class TraceSummary(TelemetryModel):
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    window: TimeRange
    services: list[ServiceKey] = Field(min_length=1, max_length=20)
    has_error: bool
    quality_status: Literal["complete", "partial", "insufficient", "unknown"]
    evidence_ids: list[str] = Field(min_length=1, max_length=3)
    root_duration_ms: float | None = Field(default=None, ge=0)
    observed_span_count: int | None = Field(default=None, ge=1)


class TraceSearchResults(TelemetryModel):
    items: list[TraceSummary] = Field(max_length=20)


class TraceResults(TelemetryModel):
    trace: EvidenceItem
    redacted_out_of_scope_spans: int = Field(ge=0)


class MetricResults(TelemetryModel):
    buckets: list[EvidenceItem] = Field(max_length=100)
    native_points: list[EvidenceItem] = Field(max_length=20)


class DependencyResults(TelemetryModel):
    edges: list[EvidenceItem] = Field(max_length=20)


class ErrorGroupResults(TelemetryModel):
    groups: list[EvidenceItem] = Field(max_length=10)
    samples: list[EvidenceItem] = Field(max_length=30)


ToolResult = (
    IncidentToolView
    | LogResults
    | TraceSearchResults
    | TraceResults
    | MetricResults
    | DependencyResults
    | ErrorGroupResults
)


class ToolResponse(TelemetryModel):
    call_id: UUID
    status: ToolStatus
    result: ToolResult | None
    failure: Failure | None
    next_cursor: str | None = Field(default=None, max_length=2048)
    provenance: Provenance
    quality_reasons: list[str] = Field(max_length=16)
    evidence_ids: list[str] = Field(max_length=400)

    @model_validator(mode="after")
    def validate_result(self) -> "ToolResponse":
        if self.status == "error" and self.failure is None:
            raise ValueError("error tool response requires failure")
        if self.status != "error" and self.result is None:
            raise ValueError("successful tool response requires result")
        return self


class ToolExecution(TelemetryModel):
    call_id: UUID
    attempt_id: UUID
    tool_name: ToolName
    arguments: ToolArguments
    started_at: str
    finished_at: str
    status: ToolStatus
    evidence_ids: list[str] = Field(max_length=100)
    failure: Failure | None = None

    _started = field_validator("started_at")(validate_utc_timestamp)
    _finished = field_validator("finished_at")(validate_utc_timestamp)


class EvidenceClaim(TelemetryModel):
    statement: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(min_length=1, max_length=8)


class SuggestedAction(TelemetryModel):
    instruction: str = Field(min_length=1, max_length=512)
    rationale: EvidenceClaim
    executed: Literal[False] = False


class InvestigationReport(TelemetryModel):
    summary: EvidenceClaim
    affected_services: list[ServiceKey] = Field(min_length=1, max_length=20)
    affected_service_claims: list[EvidenceClaim] = Field(min_length=1, max_length=20)
    suspected_root_service: ServiceKey | None = None
    root_service_claim: EvidenceClaim | None = None
    primary_hypothesis: EvidenceClaim | None = None
    supporting_evidence_ids: list[str] = Field(min_length=1, max_length=100)
    contradicting_evidence: list[EvidenceClaim] = Field(max_length=5)
    alternative_explanations: list[EvidenceClaim] = Field(max_length=3)
    confidence: Literal["low", "medium", "high"]
    confidence_rationale: str = Field(min_length=1, max_length=1000)
    recommended_next_checks: list[SuggestedAction] = Field(max_length=5)
    suggested_remediation: list[SuggestedAction] = Field(max_length=3)
    missing_evidence: list[str] = Field(max_length=10)
    limitations: list[str] = Field(max_length=10)
    completion_status: Literal["complete", "partial", "insufficient_evidence"]
    generated_at: str

    _generated = field_validator("generated_at")(validate_utc_timestamp)

    @model_validator(mode="after")
    def validate_root_and_unique_ids(self) -> "InvestigationReport":
        if (self.suspected_root_service is None) != (self.root_service_claim is None):
            raise ValueError("root service and claim must be present together")
        if len(set(self.supporting_evidence_ids)) != len(self.supporting_evidence_ids):
            raise ValueError("supporting evidence IDs must be unique")
        return self


class ProviderUsage(TelemetryModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    provider_request_id: str | None = Field(default=None, min_length=1, max_length=256)


class TextMessage(TelemetryModel):
    role: Literal["system", "user"]
    text: str = Field(min_length=1, max_length=24_000)


class ToolRequestMessage(TelemetryModel):
    role: Literal["assistant"] = "assistant"
    calls: list[ToolCall] = Field(min_length=1, max_length=2)


class ToolResultMessage(TelemetryModel):
    role: Literal["tool"] = "tool"
    response: ToolResponse


ProviderMessage = TextMessage | ToolRequestMessage | ToolResultMessage


class ToolDefinition(TelemetryModel):
    name: ToolName
    description: str = Field(min_length=1, max_length=1000)
    parameter_contract: str
    return_contract: str
    version: Literal["1.0.0"] = "1.0.0"


class GenerationRequest(TelemetryModel):
    model_id: str = Field(min_length=1, max_length=128)
    messages: list[ProviderMessage] = Field(min_length=1, max_length=50)
    tools: list[ToolDefinition] = Field(min_length=7, max_length=7)
    output_contract: Literal["InvestigationReport@1.0.0"] = "InvestigationReport@1.0.0"
    remaining_output_tokens: int = Field(ge=1, le=4000)
    deadline_at: str

    _deadline = field_validator("deadline_at")(validate_utc_timestamp)


class GenerationResponse(TelemetryModel):
    kind: Literal["tool_requests", "report", "failure"]
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=2)
    report: InvestigationReport | None = None
    failure: Failure | None = None
    usage: ProviderUsage

    @model_validator(mode="after")
    def validate_variant(self) -> "GenerationResponse":
        if self.kind == "tool_requests" and not self.tool_calls:
            raise ValueError("tool request response requires calls")
        if self.kind == "report" and self.report is None:
            raise ValueError("report response requires report")
        if self.kind == "failure" and self.failure is None:
            raise ValueError("failure response requires failure")
        return self


class InvestigationRequest(TelemetryModel):
    job_id: str = Field(pattern=r"^inv_[0-9a-f]{64}$")
    incident: Incident
    bundle: EvidenceBundle
    initial_evidence: list[EvidenceItem] = Field(min_length=1, max_length=300)
    context: ToolContext
    budget: InvestigationBudget


class InvestigationOutcome(TelemetryModel):
    report: InvestigationReport | None = None
    failure: Failure | None = None
    executions: list[ToolExecution] = Field(max_length=8)
    usage: ProviderUsage

    @model_validator(mode="after")
    def report_or_failure(self) -> "InvestigationOutcome":
        if self.report is None and self.failure is None:
            raise ValueError("investigation requires report or failure")
        return self


class InvestigationJob(TelemetryModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    investigation_id: str = Field(pattern=r"^inv_[0-9a-f]{64}$")
    incident_id: str = Field(pattern=r"^incident_[0-9a-f]{64}$")
    evidence_bundle_id: str = Field(pattern=r"^bundle_[0-9a-f]{64}$")
    evidence_version: int = Field(ge=1)
    trigger: Literal["automatic", "user"]
    requested_by: str = Field(min_length=1, max_length=128)
    idempotency_key_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_evidence_version: int | None = Field(default=None, ge=1)
    state: Literal["queued", "running", "succeeded", "failed"]
    attempt_count: int = Field(ge=0, le=3)
    attempt_id: UUID | None = None
    lease_owner: str | None = Field(default=None, min_length=1, max_length=128)
    lease_expires_at: str | None = None
    next_attempt_at: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str
    provider_id: str = Field(min_length=1, max_length=63)
    model_id: str = Field(min_length=1, max_length=128)
    prompt_version: Literal["1.0.0"] = "1.0.0"
    tool_contract_version: Literal["1.0.0"] = "1.0.0"
    additional_evidence_ids: list[str] = Field(max_length=100)
    tool_calls_used: int = Field(ge=0, le=8)
    tool_executions: list[ToolExecution] = Field(max_length=24)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    cost_limit_usd: float | None = Field(default=None, gt=0)
    additional_evidence_bytes: int = Field(default=0, ge=0, le=1_048_576)
    last_error: Failure | None = None
    report: InvestigationReport | None = None
    fixture_source: bool = False

    _lease = field_validator("lease_expires_at")(validate_optional_utc_timestamp)
    _next = field_validator("next_attempt_at")(validate_optional_utc_timestamp)
    _created = field_validator("created_at")(validate_utc_timestamp)
    _started = field_validator("started_at")(validate_optional_utc_timestamp)
    _finished = field_validator("finished_at")(validate_optional_utc_timestamp)
    _updated = field_validator("updated_at")(validate_utc_timestamp)


class InvestigationCreate(TelemetryModel):
    evidence_version: int | None = Field(default=None, ge=1)


class InvestigationAccepted(TelemetryModel):
    investigation_id: str = Field(pattern=r"^inv_[0-9a-f]{64}$")
    state: Literal["queued", "running", "succeeded", "failed"]
    incident_id: str = Field(pattern=r"^incident_[0-9a-f]{64}$")
    evidence_version: int = Field(ge=1)
    created_at: str


class InvestigationView(TelemetryModel):
    investigation_id: str = Field(pattern=r"^inv_[0-9a-f]{64}$")
    incident_id: str = Field(pattern=r"^incident_[0-9a-f]{64}$")
    evidence_version: int = Field(ge=1)
    state: Literal["queued", "running", "succeeded", "failed"]
    attempt_count: int = Field(ge=0, le=3)
    created_at: str
    started_at: str | None
    finished_at: str | None
    report: InvestigationReport | None
    failure: Failure | None
    additional_evidence: list[EvidenceItem] = Field(max_length=100)
    fixture_source: bool = False


class ProviderConfiguration(TelemetryModel):
    provider_id: str = Field(min_length=1, max_length=63)
    model_id: str = Field(min_length=1, max_length=128)
    api_key: SecretStr | None = None
