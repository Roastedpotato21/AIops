# HTTP API contracts v1

Depends on [domain.md](domain.md), [agent.md](agent.md), and [processing.md](processing.md). These declarations are Pydantic-compatible; implementation and generated OpenAPI come in the owning phases. Phase 1 implements only probes and shell behavior.

## Common rules

- Base product prefix `/api/v1`. JSON only. Reject unknown query/body fields. IDs are opaque, exact validated strings; clients cannot submit index names or storage queries.
- Product routes require authenticated principal in deployed mode. Service/environment scope is host-derived; unknown and unauthorized resource IDs both return404. Local unauthenticated shell mode must be explicit and loopback-only.
- UTC RFC3339 timestamps only; every range is `[start,end)`, start<end, end<=server_now+30s. Parameters are `start` and `end` in HTTP and map to TimeRange. Defaults computed once at request start.
- List default limit20, max100 except tighter route limit. Opaque signed cursor<=2048 characters; bound to principal, path, filters, sort and snapshot; expires in5min; expired/invalid cursor ->400. Use PIT/search_after where verified, close/expire PITs; clients never see native sort tokens.
- Deterministic sorting: time plus stable application ID; no deep offset pagination.
- Search timeout5s; total handler timeout10s excluding probe startup handling. Query partials return200 with explicit coverage; entirely unavailable required source ->503.
- No route returns LLM/provider/storage credentials, internal exception stack traces, or raw unallowlisted attributes.

## Exact envelopes

All fields below R unless N or O is specified. No generic untyped JSON appears: `result:T` is a typed Pydantic generic bound to the concrete endpoint model listed later.

| Model.field | Type | Units | Semantics | Example |
|---|---|---|---|---|
| ApiResponse.result | concrete endpoint model T | — | Successful payload | IncidentDetail |
| ApiResponse.request_id | Uuid | — | Host-generated request correlation | UUID example |
| ApiResponse.freshness | Freshness | — | Freshness of sources used, not age of an old incident itself | Below |
| ApiResponse.coverage | Coverage | — | Partial-data disclosure | Below |
| Freshness.generated_at | UtcTime | — | Response generation | T |
| Freshness.latest_source_at | UtcTime N | — | Latest relevant live source observation, null if unknown | T-5s |
| Freshness.age_seconds | float>=0 N | seconds | generated_at-latest_source_at; null if unknown | 5 |
| Freshness.state | fresh/stale/unknown/not_applicable | — | Threshold is route-specific below | `fresh` |
| Coverage.status | complete/partial/unknown | — | Known query coverage | `partial` |
| Coverage.reasons | list[ReasonCode],max16 | — | Enumerated limitations | `[source_expired]` |
| Coverage.omitted_count | int>=0 N | records | Exact omitted count if known; null otherwise | null |
| Coverage.message | string<=512 N | — | Safe explanation | `One trace source is unavailable` |
| Page.items | list[declared item type], bounded by route | — | Ordered results | `[]` |
| Page.next_cursor | string<=2048 N | — | Continuation or null | null |
| Page.has_more | bool | — | Whether another page is known to exist | false |
| ErrorResponse.request_id | Uuid | — | Correlation | UUID example |
| ErrorResponse.error | ApiError | — | Failure payload; no result | Below |
| ApiError.code | enum below | — | Stable machine code | `dependency_unavailable` |
| ApiError.message | string,1..512 | — | Safe user explanation | `OpenSearch is unavailable` |
| ApiError.retryable | bool | — | Whether caller may retry unchanged | true |
| ApiError.details | list[FieldError],max20 | — | Validation details only | `[]` |
| ApiError.active_investigation_id | Id(inv) N | — | Only for an already-active conflict | null |
| FieldError.field | string<=128 | — | Field path, not rejected secret value | `start` |
| FieldError.reason | string<=256 | — | Validation explanation | `Must be UTC` |

HTTP errors: 400 invalid_cursor; 401 unauthenticated; 404 not_found; 409 conflict/evidence_not_ready/idempotency_conflict; 422 validation_error; 429 rate_limited; 503 dependency_unavailable; 500 internal_error. These names are the complete ApiError.code enum. FastAPI default validation exceptions must be adapted to this envelope. Retry-After accompanies429/temporary503 where known. Standard request IDs may appear in probe responses but credentials must not.

Freshness: raw live telemetry >120s old is stale; finalized feature bucket end >300s old is stale; incident/investigation repository reachability is evaluated now and old historic event time is not itself stale. For a composed live response, report oldest relevant live source and disclose individual stale components in coverage. Static/historic-only responses use not_applicable when appropriate.

## Health/readiness (unwrapped)

| Route | Request | Exact response | Status behavior |
|---|---|---|---|
| GET /health | No query/body; anonymous | HealthResponse: R `status:literal "ok"`, R `service:literal "aiops-api"`, R `version:str<=128` (build ID), R `checked_at:UtcTime` | 200 if handler/process alive; no dependency calls |
| GET /ready | No query/body; anonymous or proxy-private | ReadyResponse: R `status:ready/not_ready`; R `checked_at:UtcTime`; R `checks:list[ReadinessCheck]`, max5 | 200 ready,503 otherwise; same shape for both |

ReadinessCheck fields: R `name: configuration/opensearch/bootstrap`, R `state: pass/fail`, N `reason_code: missing_config/unreachable/unauthorized/bootstrap_pending`, R `checked_at:UtcTime`. Example `opensearch,fail,unreachable,T`. No raw URLs, passwords, cluster topology, or exception messages are exposed.

Phase1 required checks: valid configuration, authenticated OpenSearch connectivity with expected single-node non-red health (green with replicas0), and bootstrap marker. Collector/Data Prepper/Dashboards health belongs to infrastructure diagnostics; LLM availability never gates API readiness. Probes are foundations, not product feature APIs.

## Read response models

Field notation here is `name: type [presence] (semantics; example)`. Inherited domain fields retain all their validation. No fields beyond those named are allowed.

| Model | Fields |
|---|---|
| ServiceSummary | `service:ServiceKey R` (identity;K); `health:ServiceHealth R` (observed health); `last_seen_at:UtcTime N` (latest event;T); `active_incident_count:int>=0 R` (open+recovering;1) |
| ServiceDetail | `summary:ServiceSummary R`; `instances:list[ServiceInstance],max100 R` (observed instances); `detectors:list[DetectorStatus],max2 R`; `latest_bucket:ServiceMetricBucket N`; `dependency_count:int>=0 N` (known one-hop count;2) |
| Overview | `overall_health:healthy/degraded/unhealthy/unknown R`; `service_counts:ServiceCounts R`; `active_incident_count:int>=0 R`; `recent_incidents:list[IncidentSummary],max10 R`; `components:list[ComponentStatus],max10 R` |
| ServiceCounts | `healthy:int>=0 R=2`, `degraded:int>=0 R=1`, `unhealthy:int>=0 R=0`, `unknown:int>=0 R=0` (counts by current health, not examples-as-defaults) |
| ComponentStatus | `name:collector/data_prepper/opensearch/aggregation/incident/investigation/detectors R`; `state:healthy/degraded/unavailable/unknown R`; `checked_at:UtcTime R`; `reason:str<=256 N` (safe diagnostic) |
| MetricsResponse | `service:ServiceKey R`; `window:TimeRange R`; `interval_seconds:literal60 R`; `requested_features:list[Feature],1..2 R`; `buckets:Page[ServiceMetricBucket] R`; `native_points:list[NativeMetricSnapshot],max20 R` |
| DependenciesResponse | `service:ServiceKey R`; `window:TimeRange R`; `edges:Page[DependencyEdge] R` |
| IncidentSummary | `incident_id:Id(incident) R`; `primary_service:ServiceKey R`; `feature:Feature R`; `state:IncidentState R`; `severity:IncidentSeverity R`; `peak_severity:IncidentSeverity R`; `detected_at:UtcTime R`; `first_affected_at:UtcTime R`; `updated_at:UtcTime R`; `evidence_status:pending/ready/partial/failed R`; `latest_investigation_id:Id(inv) N` |
| IncidentDetail | `incident:Incident R`; `evidence_bundle:EvidenceBundle N`; `timeline:Page[TimelineEntry] R`; `latest_investigation:InvestigationView N` |
| TimelineEntry | `entry_id:Id(timeline) R` (hash source event identity); `occurred_at:UtcTime R`; `kind:detected/anomaly/evidence/investigation/recovering/resolved R`; `summary:str<=512 R`; `evidence_ids:list[Id(ev)],max8 R`; `related_investigation_id:Id(inv) N` |
| EvidenceResponse | `incident_id:Id(incident) R`; `bundle:EvidenceBundle R`; `items:Page[EvidenceItem] R` |
| TraceResponse | `trace:TraceSnapshot R`; `evidence_id:Id(ev) N` (null for direct read not persisted); `out_of_scope_span_count:int>=0 R` |
| InvestigationAccepted | `investigation_id:Id(inv) R`; `state:InvestigationState R`; `incident_id:Id(incident) R`; `evidence_version:int>=1 R`; `created_at:UtcTime R` |
| InvestigationView | `investigation_id:Id(inv) R`; `incident_id:Id(incident) R`; `evidence_version:int>=1 R`; `state:InvestigationState R`; `attempt_count:int0..3 R`; `created_at:UtcTime R`; `started_at:UtcTime N`; `finished_at:UtcTime N`; `report:InvestigationReport N`; `failure:Failure N`; `additional_evidence:list[EvidenceItem],max100 R` |

Examples for nested models use K/R/T and corresponding domain examples; integer counts above illustrate values and do not set runtime defaults. All Page models inherit the exact Page fields above. IncidentSummary is a named projection, never an unrestricted partial dictionary. Internal lease ownership, provider credentials, and worker CAS tokens never appear in InvestigationView.

## Product endpoints

Query parameters not mentioned are rejected. All limit/cursor fields are optional with indicated defaults; IDs in paths are required. Shared time range fields are optional only when a default is stated.

| Endpoint | Query/body contract | Success response T in ApiResponse[T] | Ordering / limits |
|---|---|---|---|
| GET /api/v1/overview | `namespace:Label` O=authorized default; `environment:Label` O=authorized default | Overview | Latest10 incidents; counts scoped; overall health precedence unknown if any mandatory coverage unknown, else unhealthy >degraded >healthy |
| GET /api/v1/services | namespace/environment as above; `health:ServiceHealth.state` O=null; `limit:int1..100` O=20; cursor O=null | Page[ServiceSummary] | service_id ascending; unknown services remain visible |
| GET /api/v1/services/{service_id} | No query | ServiceDetail | Instances capped100; partial if more |
| GET /api/v1/services/{service_id}/metrics | start/end O=last60min; max24h; `features:list[Feature],1..2` O=both; `include_native:bool` O=false; `limit:int1..120` O=60; cursor O=null | MetricsResponse | window.start ascending then bucket_id; no larger interval in v1; native names host-allowlisted |
| GET /api/v1/services/{service_id}/dependencies | start/end O=last15min; max1h; `direction:upstream/downstream/both` O=both; limit1..50 O=20; cursor | DependenciesResponse | source_service_id,target_service_id,window.start,edge_id |
| GET /api/v1/incidents | namespace/environment; `state:IncidentState` O=null; `severity:IncidentSeverity` O=null; `service_id:Id(svc)` O=null; start/end O=last24h, max30d; limit1..100 O=20; cursor | Page[IncidentSummary] | Filters detected_at in range, service matches affected_services; detected_at descending then incident_id |
| GET /api/v1/incidents/{id} | `timeline_limit:int1..50` O=20; `timeline_cursor:str<=2048` O=null | IncidentDetail | Timeline occurred_at ascending,entry_id; no invented times when historical evidence was late |
| GET /api/v1/incidents/{id}/evidence | `bundle_version:int>=1` O=latest; `type:EvidenceSnapshot.kind` O=null; limit1..50 O=20; cursor | EvidenceResponse | Bundle ID pinned by first page; stored evidence_ids order; return partial/source_expired if missing references |
| GET /api/v1/traces/{trace_id} | `service_id:Id(svc)` R; start/end R,max30min; `max_spans:int1..200` O=100 | TraceResponse | Scope authorization and trace intersection required; parent-before-child if reconstructable, then time/span_id; partial if gaps |
| POST /api/v1/incidents/{id}/investigate | Header `Idempotency-Key:str1..128` R, printable ASCII; body InvestigationCreate below | InvestigationAccepted; **202** | Persist first; Location=/api/v1/investigations/{id}; no inline provider work |
| GET /api/v1/investigations/{id} | No query | InvestigationView | 200 for queued/running/succeeded/failed persisted jobs |

InvestigationCreate: **O** `evidence_version:int>=1|null` default null (server resolves current committed bundle), example1. No prompt, provider, model, instruction, tool override, scope override, or force flag is accepted. Empty `{}` is valid. If no committed bundle, return409 evidence_not_ready. Job quota/rate limits ->429; active different job ->409 conflict. Exact idempotent retry always returns original record, including its originally selected evidence version, never re-resolves a newer bundle. Store effective-body digest and original request's version-selection mode so the same literal request is recognized after incident updates.

Examples of concrete response contents: metrics bucket contains latency_p95_ms in milliseconds and error_rate as a fraction; `InvestigationAccepted` contains an actual persisted `inv_...` ID with state queued; a failed job remains a200 InvestigationView with state failed and a typed failure. These are semantics, not mocked runtime endpoints.

## Timeline persistence boundary

No new datastore/index is introduced. Timeline is a bounded projection of incident state-transition entries (storage envelope), assigned anomalies, committed bundles, and investigations. State-transition entries are capped at100 per incident; preserve first detection, latest recovery/resolution and mark older omitted entries as truncated. The current state remains authoritative. API cursor spans this deterministic merged projection; implementation may materialize within incident document limits, never unbounded arrays.

## Browser boundary

Frontend uses generated OpenAPI types and these DTOs. It never receives raw OpenSearch responses or credentials. It displays uncertainty, staleness, failed jobs, approximate percentiles, and incomplete traces explicitly. Polling suffices; no streaming/websocket contract is required for beta. Phase 1 frontend is a neutral shell displaying only API health/readiness, not fake incidents or feature pages.
