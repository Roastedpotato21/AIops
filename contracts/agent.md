# Read-only agent contracts v1

Types, R/N/O notation, timestamps, examples, and validation are inherited from [domain.md](domain.md). This document specifies interfaces, not application code or a framework dependency.

## Interfaces

| Interface | Exact logical signature | Behavior |
|---|---|---|
| Investigator.investigate | async `(request: InvestigationRequest, tools: ToolRegistry, provider: ReasoningProvider) -> InvestigationOutcome` | Bounded orchestration; returns validated report or typed failure; does not directly persist or operate infrastructure |
| ToolRegistry.execute | async `(call: ToolCall, context: ToolContext) -> ToolResponse[registered return type]` | Host validates name, parameters, auth scope, budget and limits before query; read-only repository methods only |
| ReasoningProvider.generate | async `(request: GenerationRequest) -> GenerationResponse` | Adapter handles one provider round; normalizes structured output/tool requests and usage; no automatic tool execution |

All I/O methods accept a host cancellation/deadline mechanism; cancellation propagates to search/provider calls. Tool/provider exceptions are converted to Failure, never passed through as raw stack traces.

### Investigation request, scope, budget, and result

| Model.field | Type | Presence/default | Units | Semantics | Example |
|---|---|---|---|---|---|
| InvestigationRequest.job_id | Id(inv) | R | — | Persisted job being executed | `inv_<hash>` |
| InvestigationRequest.incident | Incident | R | — | Snapshot at job start, not mutable live object | Domain example |
| InvestigationRequest.bundle | EvidenceBundle | R | — | Pinned revision | Domain example |
| InvestigationRequest.initial_evidence | list[EvidenceItem],1..300 | R | — | Items actually loaded, within bundle limits | `[anomaly evidence, bucket evidence]` |
| InvestigationRequest.context | ToolContext | R | — | Host-generated authorized context | Below |
| InvestigationRequest.budget | InvestigationBudget | R | — | Non-model-controlled upper limits | Below |
| ToolContext.principal_id | string,1..128 | R | — | Authenticated initiating principal/system | `system` |
| ToolContext.job_id | Id(inv) | R | — | Audit/job correlation | `inv_<hash>` |
| ToolContext.incident_id | Id(incident) | R | — | Only readable incident for this run | `incident_<hash>` |
| ToolContext.allowed_service_ids | list[Id(svc)],1..20 | R | — | Primary/affected + verified one-hop neighbors, same namespace/environment | `[svc_<hash>]` |
| ToolContext.allowed_window | TimeRange | R | — | Host fixes <=30min around this bundle; model cannot expand | R |
| ToolContext.deadline_at | UtcTime | R | — | Absolute attempt deadline | T+60s |
| ToolContext.evidence_allowlist | list[Id(ev)],max400 | R | — | Initial plus host-persisted retrieved evidence, updated by host only | `[ev_<hash>]` |
| InvestigationBudget.max_tool_calls | int 1..8 | O=8 | calls/attempt | Every call, including failed and paginated calls, counts | 8 |
| InvestigationBudget.max_provider_rounds | int 1..6 | O=6 | rounds/attempt | Includes output repair | 6 |
| InvestigationBudget.max_input_tokens | int 1..24000 | O=24000 | tokens/attempt | Cumulative provider input; estimate before dispatch, reconcile usage | 24000 |
| InvestigationBudget.max_output_tokens | int 1..4000 | O=4000 | tokens/attempt | Cumulative provider output | 4000 |
| InvestigationBudget.max_duration_seconds | int 1..60 | O=60 | seconds/attempt | Includes tools and provider | 60 |
| InvestigationBudget.max_cost_usd | float>0 | N | USD/job | Optional configured whole-job ceiling; unknown rate means no reliable cost estimate, token limits still enforced | 0.50 |
| InvestigationBudget.max_additional_evidence_bytes | int 1..1048576 | O=1048576 | bytes/job | Across retries, on top of initial bundle | 1048576 |
| InvestigationOutcome.report | InvestigationReport | N | — | Validated result, including partial/insufficient | Domain example |
| InvestigationOutcome.failure | Failure | N | — | Terminal/no-report reason, or limitation alongside partial report | null |
| InvestigationOutcome.executions | list[ToolExecution],max8 | R | — | Audit of this attempt | `[]` |
| InvestigationOutcome.usage | ProviderUsage | R | — | Attempt's summed normalized usage | Below |

At least report or failure is non-null. Report completion_status describes investigation quality; job state describes execution success. A validated partial report is a succeeded job with limitations, not a fictional completed analysis. If no supported report can be produced, fail the job.

### Tool call, response, and execution

| Model.field | Type | Presence | Units | Semantics | Example |
|---|---|---|---|---|---|
| ToolCall.call_id | Uuid | R | — | Host-normalized call correlation | UUID example |
| ToolCall.name | enum of seven names below | R | — | Allowlisted selector | `search_logs` |
| ToolCall.arguments | registered parameter model for name | R | — | Discriminated/validated, no dictionary escape hatch | SearchLogsParams |
| ToolResponse.call_id | Uuid | R | — | Echo call ID | UUID example |
| ToolResponse.status | enum `ok`, `empty`, `partial`, `error` | R | — | Success/completeness state | `partial` |
| ToolResponse.result | registered return model for name | N | — | Exact model specified below; null only on error | LogResults |
| ToolResponse.failure | Failure | N | — | Structured tool failure; may coexist with partial results | null |
| ToolResponse.next_cursor | string,1..2048 | N | — | Opaque bounded continuation token | null |
| ToolResponse.provenance | Provenance | R | — | Effective query and snapshot | Domain example |
| ToolResponse.quality_reasons | list[ReasonCode],max16 | R | — | Truncation/gaps/error status | `[truncated]` |
| ToolResponse.evidence_ids | list[Id(ev)],max400 | R | — | Host-validated persisted IDs available to cite; at most100 new items/job | `[ev_<hash>]` |
| ToolExecution.call_id | Uuid | R | — | Executed call | UUID example |
| ToolExecution.attempt_id | Uuid | R | — | Owning worker attempt | UUID example |
| ToolExecution.tool_name | enum tool names | R | — | Audit selector | `get_metrics` |
| ToolExecution.arguments | registered parameter model | R | — | Sanitized typed effective arguments | MetricsParams |
| ToolExecution.started_at | UtcTime | R | — | Start | T |
| ToolExecution.finished_at | UtcTime | R | — | End | T+0.2s |
| ToolExecution.status | same as ToolResponse.status | R | — | Outcome | `ok` |
| ToolExecution.evidence_ids | list[Id(ev)],max100 | R | — | Returned references | `[ev_<hash>]` |
| ToolExecution.failure | Failure | N | — | Sanitized error | null |

ToolExecution entries are stored in InvestigationJob as required `tool_executions:list[ToolExecution]`, max24 (8 calls x3 attempts), example `[]`. This is an explicit extension of the job table in domain.md. Total serialized job <=512KiB; truncate safe error/text diagnostics before omitting audit IDs. More than the cap fails validation.

### Shared parameter rules

Query parameters below are all the allowed fields. No `query`, `index`, `url`, `script`, `command`, or unrestricted attribute filters are accepted.

- `service_ids`: list[Id(svc)], 1..5, **R**; unique; subset of ToolContext; example `[svc_<hash>]`.
- `window`: TimeRange, **R**; <=30 minutes; contained in allowed_window; example R.
- `cursor`: string<=2048, **O=null**; signature bound to principal/job/name/effective arguments/snapshot, expires after 5 minutes; invalid/expired ->invalid_argument. Tokens cannot expand scope.
- `limit`: integer, **O** with per-tool defaults below; records, not bytes. The response cap is 256KiB/tool and 100 new EvidenceItems/job; remaining budget may reduce returned count and cause partial.
- All tool repository calls have a 5-second timeout or remaining attempt time, whichever is smaller.

## Exact tools

| Tool | Parameter model (presence, defaults, examples) | Return model (all fields R unless N) | Limits and partial behavior |
|---|---|---|---|
| get_incident | `incident_id: Id(incident)` R; must equal context.incident_id | IncidentToolView: `incident:Incident`; `bundle:EvidenceBundle`; `evidence_ids:list[Id(ev)],max300` | No pagination; pinned snapshot/bundle only; referenced expired evidence produces partial |
| search_logs | Shared service_ids/window; `severity_min: DEBUG/INFO/WARN/ERROR/FATAL` O=ERROR; `trace_id:TraceId` O=null; `text_contains:str<=256` O=null (literal text); `limit:int1..50` O=20; cursor O=null | LogResults: `items:list[EvidenceItem of log_record],max50` | Stable event_time + source ID sort; redacted body<=4096; empty means no observed matches, not no failures |
| search_traces | Shared service_ids/window; `status: error/ok` O=null; `min_duration_ms:float>=0` O=null; `limit:int1..20` O=10; cursor O=null | TraceSearchResults: `items:list[TraceSummary],max20` | Search summary only; duration is observed root server duration if root is present, else null; never sum span durations |
| get_trace | `trace_id:TraceId` R; `max_spans:int1..200` O=100 | TraceResults: `trace:EvidenceItem of trace`; `redacted_out_of_scope_spans:int>=0` | No pagination; requested trace must intersect authorized scope/window; remove unauthorized spans; flags include missing root/parents and truncation |
| get_metrics | Shared service_ids/window; `features:list[Feature],1..2` O=[latency_p95_ms,error_rate]; `include_native:bool` O=false; `limit:int1..100` O=60; cursor O=null | MetricResults: `buckets:list[EvidenceItem of metric_bucket],max100`; `native_points:list[EvidenceItem of native_metric],max20` | Combined requested page limit applies; bucket interval fixed60s; no arbitrary rollups; native names from host allowlist |
| get_service_dependencies | `service_id:Id(svc)` R; window R; `direction: upstream/downstream/both` O=both; `limit:int1..20` O=20; cursor O=null | DependencyResults: `edges:list[EvidenceItem of dependency_edge],max20` | One hop only; no arbitrary graph depth; neighbors outside authorized namespace/environment omitted |
| find_related_errors | Shared service_ids/window; `trace_id:TraceId` O=null; `limit:int1..10` O=5; cursor O=null | ErrorGroupResults: `groups:list[EvidenceItem of error_group],max10`; `samples:list[EvidenceItem of log_record],max30` | Group normalized error type + redacted template; <=3 actual samples/group; counts over bounded query interval, not estimated global frequency |

TraceSummary value object fields: **R** `trace_id:TraceId`, `window:TimeRange`, `services:list[ServiceKey],1..20`, `has_error:bool`, `quality_status:QualityStatus`, `evidence_ids:list[Id(ev)],1..3`; **N** `root_duration_ms:float>=0` in ms; **N** `observed_span_count:int>=1`. Example: trace ID from domain, R, [K], true, partial, [span evidence], null, 7. Supporting selected span evidence is persisted before returning a summary; citations never point to an unpersisted search hit.

Native metric allowlist v1: application request histogram/count if verified SDK semantics are known, `process.cpu.utilization`, `process.memory.usage`, and a configured `aiops.telemetry.heartbeat` gauge. Bind each name to verified unit/type/temporality in the metric registry. Unsupported/absent metrics return empty or unsupported_metric; never synthesize. Native histogram evidence is descriptive; v1 RCF still consumes only server-span buckets.

Error grouping normalization v1: use structured exception type (else `unknown`), redact secret patterns, replace UUIDs and decimal digit runs with placeholders, collapse whitespace, truncate template to512; fingerprint H("errorgroup",[service_id,error_type,message_template,normalization_version]). Exclude DEBUG/INFO/WARN from error groups. Pin normalization_version=1.0.0.

All tools return Failure codes as applicable: invalid_argument, forbidden, not_found, timeout, unavailable, source_expired, budget_exhausted, unsupported_metric. A backend query with partial shards returns partial and actual available evidence; an entirely failed query returns error and null result. `empty` is only a successful zero-match query. Pagination calls count toward tool budget. No tool returns raw credentials or unrestricted attributes.

For a failed query, provenance.retrieved_at records attempt completion and source_cutoff the attempted snapshot bound; status=error makes clear that no successful observation occurred. All effective filter fields are recorded, unused optional filters are null and unused lists empty. get_trace returns only spans intersecting the allowed window and authorized service scope; an intersecting trace ID is not permission to retrieve its other environments or unlimited history.

## Provider contract

| Model.field | Type | Presence | Units | Semantics | Example |
|---|---|---|---|---|---|
| GenerationRequest.model_id | string,1..128 | R | — | Host-selected provider model | `configured-model` |
| GenerationRequest.messages | list[ProviderMessage],1..50 | R | — | Bounded conversation, tools represented as typed results | Below |
| GenerationRequest.tools | list[ToolDefinition],exact7 | R | — | Host-supplied allowlist | Seven tools above |
| GenerationRequest.output_contract | literal `InvestigationReport@1.0.0` | R | — | Adapter compiles approved schema, not model-supplied schema | literal |
| GenerationRequest.remaining_output_tokens | int1..4000 | R | tokens | Limit for this call, <=remaining attempt budget | 1000 |
| GenerationRequest.deadline_at | UtcTime | R | — | Earlier of per-call and attempt deadline | T+30s |
| GenerationResponse.kind | enum `tool_requests`, `report`, `failure` | R | — | Tagged result | `tool_requests` |
| GenerationResponse.tool_calls | list[ToolCall],max2 | R | — | Empty unless tool_requests; >=1 when tool_requests | `[call]` |
| GenerationResponse.report | InvestigationReport | N | — | Candidate report; host still validates | null |
| GenerationResponse.failure | Failure | N | — | Required iff failure | null |
| GenerationResponse.usage | ProviderUsage | R | — | Reported usage | Below |
| ProviderUsage.input_tokens | int>=0 | N | tokens | Null if provider did not report; enforce estimated bound anyway | 1500 |
| ProviderUsage.output_tokens | int>=0 | N | tokens | Same | 300 |
| ProviderUsage.cost_usd | float>=0 | N | USD | Verified rate calculation only | null |
| ProviderUsage.provider_request_id | string,1..256 | N | — | Safe provider correlation identifier | `request-123` |

ProviderMessage is a closed union: TextMessage (**R** role=`system` or `user`, **R** text:str<=24000, example redacted instructions/evidence summary); ToolRequestMessage (**R** role=`assistant`, **R** calls:list[ToolCall],1..2); ToolResultMessage (**R** role=`tool`, **R** response:ToolResponse). No hidden reasoning transcript is persisted or required. The adapter may translate these types to its provider's format without changing permissions.

ToolDefinition: **R** name=tool-name enum, **R** description:str<=1000 (human semantics), **R** parameter_contract:string from the seven declared parameter-model names, **R** return_contract:string from the seven declared return-model names, **R** version:Version=1.0.0. Adapters generate JSON Schema from the approved typed models later; model cannot add schemas/tools dynamically.

Unknown fields, invalid enum/ID, out-of-scope service, nonexistent citation, and attempted write operations fail validation. Permit one output repair round inside existing call/time/token budget for malformed schema/citations; never grant more capabilities. If repair fails, job fails invalid_output/invalid_citation. If budget/time expires with a valid supported partial report, persist it; otherwise fail explicitly. A test/fake provider identifies itself as such and never substitutes for live-provider acceptance.

## Report integrity and operational limits

- Every material claim references persisted evidence from the pinned bundle or job additions. Citation existence is checked against authorized IDs and content remains available at report commit.
- Affected/root service assertions require corresponding claims and actual scope membership. The root may remain null; abstention is valid.
- Recommendations and remediation are SuggestedAction records with executed=false. Tools cannot write or call infrastructure.
- Log/span text is untrusted input. It cannot override system constraints or supply URLs, tool names, credentials, or execution instructions.
- Provider sees a selected redacted subset within token budget, not whole raw indexes. Deterministic selection/truncation is disclosed in limitations.
- Use read-only OpenSearch credentials for tool repositories; host storage credentials are not placed in provider context or ToolContext.
- No filesystem, shell, HTTP fetch, arbitrary DSL, AWS, GitHub, deployment, or write capability is registered.
- A whole-job cost cap requires verified rate metadata; if configured and rate information is unavailable, refuse live execution with a clear configuration failure. Without cost cap, token/time budgets still apply and cost_usd may be null.
