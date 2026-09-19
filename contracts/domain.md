# Domain contracts v1

## Schema notation and common validation

These are normative Pydantic-compatible schemas, not Python implementations. Models use `extra="forbid"`, explicit nested models, finite floats, and strict booleans/integers (a boolean is not an integer). No arbitrary `data`, `metadata`, or `score` fields exist.

Field presence: **R** = required and non-null; **N** = required key, value may be null; **O** = optional on input with the stated default. Persisted and response models emit all declared keys, including nulls. Arrays use `[]` rather than null. Defaults apply only where specified. Units `—` mean not applicable.

| Type | Constraints / semantics | Example |
|---|---|---|
| `UtcTime` | RFC3339 UTC string with 0..9 fractional digits; accepts only `Z` or `+00:00`, emits `Z`; validate/compare using integer epoch nanoseconds and preserve source precision | `2026-09-19T12:00:00Z` |
| `TimeRange` | Required `start: UtcTime`, `end: UtcTime`; `start < end`; half-open `[start,end)` | `{"start":"2026-09-19T12:00:00Z","end":"2026-09-19T12:01:00Z"}` |
| `Id` | Lowercase type prefix + full 64-character lowercase SHA-256 hex digest; opaque to clients | `svc_<64 hex>` |
| `Uuid` | Canonical lowercase UUID string; use UUIDv4 for random request/attempt IDs | `550e8400-e29b-41d4-a716-446655440000` |
| `TraceId` | 32 lowercase hex characters, not all zero | `4bf92f3577b34da6a3ce929d0e0e4736` |
| `SpanId` | 16 lowercase hex characters, not all zero | `00f067aa0ba902b7` |
| `Label` | Case-sensitive ASCII `[A-Za-z0-9][A-Za-z0-9._-]{0,62}`; no implicit case folding/whitespace trimming | `payment-service` |
| `Version` | SemVer string for application contract/config versions | `1.0.0` |
| `Ratio` | Finite float in `[0,1]`; fraction, never percent | `0.05` |
| `Feature` | `latency_p95_ms` or `error_rate` | `error_rate` |
| `QualityStatus` | `complete`, `partial`, `insufficient`, `unknown`; complete means satisfies known contract checks, not proof of lossless observation | `partial` |
| `IncidentSeverity` | `low`, `medium`, `high`, `critical`; increasing observed operational impact, not model probability | `high` |
| `IncidentState` | `open`, `recovering`, `resolved` | `open` |
| `InvestigationState` | `queued`, `running`, `succeeded`, `failed`; partial report may exist in a succeeded job | `queued` |
| `Confidence` | `low`, `medium`, `high`; qualitative judgment only | `low` |
| `ReasonCode` | Closed enum: `low_sample_count`, `no_spans`, `sampling_enabled`, `pipeline_stale`, `query_partial`, `invalid_span`, `late_data`, `duplicate_conflict`, `missing_http_status`, `source_expired`, `truncated`, `clock_skew`, `detector_unready`, `baseline_missing`, `tool_failure`, `budget_exhausted`, `unobserved_service`, `redaction_applied` | `truncated` |

All examples using `<64 hex>`, `K`, `T`, `R`, or short IDs are explanatory substitutions, not valid literal production IDs. **K** means the ServiceKey example below; **T** is `2026-09-19T12:00:00Z`; **R** is `[T,2026-09-19T12:01:00Z)`. Examples do not claim observed telemetry.

UtcTime is implementable as an annotated validated string/custom Pydantic type. Do not silently pass nanosecond identity inputs through Python datetime, which would discard precision beyond microseconds. Normalize event identity separately from database date precision. Reject leap-second notation rather than normalizing it differently in separate services.

ID function `H(prefix, parts)` = `prefix + "_" + SHA256(UTF8(canonical JSON array(parts)))`. Canonical JSON here means compact separators, ASCII-escaped strings, no whitespace, array order preserved, integer decimal form; identity inputs are strings or integers only. Normalize time identity inputs to integer epoch nanoseconds represented as decimal **strings**. Never hash display summaries. Exact identities are specified in processing.md.

All stored domain documents also carry `schema_version: Version` (**R**, —, schema version, example `1.0.0`). This inherited field is not repeated in every table. API leaf models use the same version where they represent stored domain documents. Value objects such as TimeRange do not acquire this field.

## ServiceKey

| Field | Type | Presence | Units | Semantics | Example |
|---|---|---|---|---|---|
| service_id | Id (`svc`) | R | — | `H("svc",[namespace,environment,name])`; validator recomputes | `svc_<64 hex>` |
| namespace | Label | R | — | Application namespace; explicit, never inferred from service name | `demo-shop` |
| environment | Label | R | — | Deployment scope; cross-environment correlation forbidden | `development` |
| name | Label | R | — | OTel service name | `payment-service` |

ServiceKey is a value object without `schema_version`. Namespace and environment must be attached to telemetry at ingestion; missing identity is quarantined, not grouped under a shared default.

## ServiceInstance

| Field | Type | Presence | Units | Semantics | Example |
|---|---|---|---|---|---|
| instance_record_id | Id (`inst`) | R | — | Hash of service ID and instance ID | `inst_<64 hex>` |
| service | ServiceKey | R | — | Logical service | K |
| instance_id | string, 1..128 | R | — | OTel `service.instance.id`; new on process/container incarnation | `payment-7c932` |
| service_version | string, 1..128 | N | — | Application release label, not required to be SemVer | `git-a1b2c3d` |
| first_seen_at | UtcTime | R | — | Earliest observed event for this incarnation | T |
| last_seen_at | UtcTime | R | — | Latest observed event time, >= first_seen_at | `2026-09-19T12:05:00Z` |
| last_ingested_at | UtcTime | R | — | Latest receiver observation time | `2026-09-19T12:05:03Z` |

This is an API/query projection from telemetry, not a mandatory extra index. Instance labels, hostnames, or arbitrary resource attributes are not authorization boundaries.

## ServiceMetricBucket

| Field | Type | Presence | Units | Semantics | Example |
|---|---|---|---|---|---|
| bucket_id | Id (`bucket`) | R | — | Service + minute start + aggregation version | `bucket_<64 hex>` |
| service | ServiceKey | R | — | Aggregation scope; all instances combined | K |
| window | TimeRange | R | — | UTC minute aligned; exactly 60 seconds | R |
| bucket_time | UtcTime | R | — | Equals window.start; detector time field | T |
| request_count | int >= 0 | R | requests | Count of unique included completed SERVER spans | 100 |
| error_count | int >= 0 | R | requests | Included spans classified as server errors; <= request_count | 5 |
| error_rate | Ratio | N | fraction | error_count / request_count; null when denominator is 0 | 0.05 |
| latency_mean_ms | float >= 0 | N | ms | Sum of included durations / request_count; null if zero | 125.4 |
| latency_p95_ms | float >= 0 | N | ms | OpenSearch TDigest p95; null if zero | 240.1 |
| source_count | int >= 0 | R | spans | Number of unique spans used; equals request_count in v1 | 100 |
| invalid_span_count | int >= 0 | R | spans | Candidates rejected for structural/duration/status problems | 0 |
| late_span_count | int >= 0 | R | spans | Known eligible spans discovered after finalization; feature values remain frozen | 0 |
| quality_status | QualityStatus | R | — | Rules in processing.md | `complete` |
| quality_reasons | list[ReasonCode], max 16, unique | R | — | Machine-readable limitations | `[]` |
| eligible_for_detection | bool | R | — | True only at finalization with complete quality and >=20 samples | true |
| source_kind | literal `server_spans` | R | — | Explicit feature provenance | `server_spans` |
| aggregation_version | Version | R | — | Inclusion/math/finalization policy version | `1.0.0` |
| sampling_fraction | Ratio | N | fraction | Configured retention fraction; null if unknown; v1 detection requires 1 | 1.0 |
| computed_at | UtcTime | R | — | When the feature values were calculated | `2026-09-19T12:02:30Z` |
| finalized_at | UtcTime | N | — | Immutable feature-value publication time; null for provisional bucket | `2026-09-19T12:02:30Z` |
| source_visible_through | UtcTime | R | — | Ingestion cutoff/snapshot time used for finalization, not a guarantee of completeness | `2026-09-19T12:02:30Z` |

## DetectorStatus and Anomaly

`DetectorStatus` is a projection of native plugin status plus input checks; not a replacement RCF implementation.

| DetectorStatus field | Type | Presence | Units | Semantics | Example |
|---|---|---|---|---|---|
| detector_id | string, 1..256 | R | — | Native plugin identifier | `native-detector-id` |
| detector_name | string, 1..256 | R | — | Versioned human-readable name | `aiops-svc-<hash>-latency-v1` |
| service | ServiceKey | R | — | Detector scope | K |
| feature | Feature | R | — | Sole detector feature | `latency_p95_ms` |
| config_version | Version | R | — | Detector configuration version | `1.0.0` |
| state | enum `not_started`, `warming_up`, `ready`, `insufficient_data`, `failed`, `stopped` | R | — | Precedence/rules in processing.md | `warming_up` |
| checked_at | UtcTime | R | — | Last successful status observation | T |
| last_result_at | UtcTime | N | — | Most recent result execution end | T |
| reason | string, max 512 | N | — | Sanitized explanation of non-ready state | `No eligible input for latest interval` |

| Anomaly field | Type | Presence | Units | Semantics | Example |
|---|---|---|---|---|---|
| anomaly_id | Id (`anomaly`) | R | — | Hash of native result physical index and document ID | `anomaly_<64 hex>` |
| detector_id | string, 1..256 | R | — | Native identifier | `native-detector-id` |
| detector_name | string, 1..256 | R | — | Registered detector name | `aiops-svc-<hash>-errors-v1` |
| detector_config_version | Version | R | — | Immutable registry association, not inferred from current config | `1.0.0` |
| service | ServiceKey | R | — | From validated detector registry | K |
| feature | Feature | R | — | Input feature | `error_rate` |
| feature_value | float >= 0 | N | feature unit | Native aggregate; error_rate additionally <=1 | 0.2 |
| input_bucket_id | Id (`bucket`) | N | — | Unique matching source bucket; null if absent/ambiguous | `bucket_<64 hex>` |
| detector_window | TimeRange | R | — | Native data_start_time/data_end_time | R |
| affected_window | TimeRange | N | — | Actual source bucket window; correlation uses this | R |
| execution_started_at | UtcTime | R | — | Native scheduling/execution start | `2026-09-19T12:04:00Z` |
| execution_ended_at | UtcTime | R | — | Native execution end; polling time key | `2026-09-19T12:04:01Z` |
| anomaly_grade | Ratio | N | fraction | Native RCF anomaly grade; missing is not zero | 0.8 |
| detector_confidence | Ratio | N | fraction | Native model confidence, not diagnosis confidence | 0.9 |
| result_status | enum `anomalous`, `normal`, `insufficient_data`, `failed` | R | — | Normalized validity and native positive-grade classification | `anomalous` |
| error_reason | string, max 512 | N | — | Sanitized native/normalization failure | null |
| source | DocumentLocator | R | — | Native result reference | See locators |
| observed_at | UtcTime | R | — | First normalized ingestion time; stable across replay | `2026-09-19T12:04:10Z` |

The Anomaly collection includes normal/failed/insufficient results for progress and diagnosis; only `anomalous` opens an incident.

## Incident value objects

| Model.field | Type | Presence | Units | Semantics | Example |
|---|---|---|---|---|---|
| RecoveryBaseline.window | TimeRange | R | — | Up to 30 minutes immediately before first affected minute | `[11:30Z,12:00Z)` |
| RecoveryBaseline.bucket_ids | list[Id (`bucket`)], 10..30 | R | — | Eligible non-anomalous source minutes used | `[bucket_<hash>, ...]` |
| RecoveryBaseline.latency_p95_median_ms | float >= 0 | R | ms | Median of minute p95 values; not overall p95 | 210 |
| RecoveryBaseline.error_rate_median | Ratio | R | fraction | Median of minute error rates | 0 |
| RecoveryBaseline.captured_at | UtcTime | R | — | Frozen baseline creation | `2026-09-19T12:04:10Z` |
| RelatedIncident.incident_id | Id (`incident`) | R | — | Linked episode | `incident_<hash>` |
| RelatedIncident.reason | enum `shared_trace`, `dependency_and_overlap`, `same_service_overlap` | R | — | Correlation evidence, never causality | `shared_trace` |
| RelatedIncident.evidence_ids | list[Id (`ev`)], 1..8 | R | — | Supporting links/trace snapshots | `[ev_<hash>]` |
| RelatedIncident.linked_at | UtcTime | R | — | When link was established | T |

## Incident

| Field | Type | Presence | Units | Semantics | Example |
|---|---|---|---|---|---|
| incident_id | Id (`incident`) | R | — | Hash of scope + feature + opening anomaly ID + policy version | `incident_<64 hex>` |
| primary_service | ServiceKey | R | — | Service on opening detector, not root cause | K |
| affected_services | list[ServiceKey], 1..20 | R | — | Primary plus evidence-backed affected services, sorted by service_id | `[K]` |
| feature | Feature | R | — | Episode symptom key | `error_rate` |
| state | IncidentState | R | — | Lifecycle independent of investigation state | `open` |
| severity | IncidentSeverity | R | — | Current deterministic impact classification | `high` |
| severity_reason | string, max 512 | R | — | Values and policy branch causing severity | `error_rate 0.10 >= 0.05; 100 requests` |
| severity_bucket_ids | list[Id (`bucket`)], max 5 | R | — | Inputs used in latest severity assessment | `[bucket_<hash>]` |
| opened_by_anomaly_id | Id (`anomaly`) | R | — | Immutable initial trigger | `anomaly_<hash>` |
| anomaly_count | int >= 1 | R | results | Count of distinct linked positive results, not poll count | 3 |
| recent_anomaly_ids | list[Id (`anomaly`)], 1..100 | R | — | Most recent distinct IDs; full links live with normalized result processing state | `[anomaly_<hash>]` |
| related_incidents | list[RelatedIncident], max 20 | R | — | Non-causal links | `[]` |
| first_affected_at | UtcTime | R | — | Earliest linked bucket start; may move earlier after late result | T |
| last_affected_at | UtcTime | R | — | Latest linked anomalous bucket end | `2026-09-19T12:03:00Z` |
| detected_at | UtcTime | R | — | First incident persistence time; immutable | `2026-09-19T12:04:10Z` |
| updated_at | UtcTime | R | — | Latest material persisted change | `2026-09-19T12:05:10Z` |
| recovering_since | UtcTime | N | — | Start of current verified healthy streak, set at recovery transition | null |
| resolved_at | UtcTime | N | — | Observation time when resolution criteria passed | null |
| recovery_baseline | RecoveryBaseline | N | — | Frozen pre-incident reference; null prevents auto-resolution | null |
| healthy_bucket_streak | int >= 0 | R | minutes | Consecutive verified healthy one-minute buckets | 0 |
| last_recovery_bucket_end | UtcTime | N | — | Last minute accounted for; prevents replay increment | null |
| suspected_root_service | ServiceKey | N | — | Initial value null; deterministic core never promotes an LLM opinion here | null |
| suspected_root_evidence_ids | list[Id (`ev`)], max 8 | R | — | Empty while core suspected_root_service is null | `[]` |
| latest_evidence_bundle_id | Id (`bundle`) | N | — | Latest committed immutable bundle; null during collection | `bundle_<hash>` |
| evidence_version | int >= 0 | R | revision | Starts 0, increments on materially changed committed bundle | 1 |
| evidence_status | enum `pending`, `ready`, `partial`, `failed` | R | — | Collection state, not incident lifecycle | `ready` |
| latest_investigation_id | Id (`inv`) | N | — | Latest scheduled investigation; runner reconciles pointer | null |
| policy_version | Version | R | — | Incident/severity/recovery policy | `1.0.0` |

Agent root-service candidates remain in InvestigationReport and are displayed as hypotheses; this avoids nondeterministic mutation of core incident conclusions. v1 keeps core suspected_root_service null. A later deterministic attribution policy requires a versioned contract change.

## Evidence locators and provenance

No locator may contain a URL, credentials, filesystem path, or arbitrary query DSL. Physical index names are internal storage references, not tool arguments.

| Model.field | Type | Presence | Units | Semantics | Example |
|---|---|---|---|---|---|
| DocumentLocator.kind | literal `document` | R | — | Union discriminator | `document` |
| DocumentLocator.index | string, 1..255 | R | — | Exact physical source index, resolved by trusted adapter | `aiops-logs-v1-000001` |
| DocumentLocator.document_id | string, 1..512 | R | — | Exact source `_id` | `log_<hash>` |
| DocumentLocator.source_version | string, max 128 | N | — | Native seq_no/primary_term or content hash at retrieval | `12:1` |
| TraceLocator.kind | literal `trace` | R | — | Union discriminator | `trace` |
| TraceLocator.trace_id | TraceId | R | — | Trace being reconstructed | `4bf92f3577b34da6a3ce929d0e0e4736` |
| TraceLocator.index_alias | string, 1..255 | R | — | Trusted configured trace alias | `otel-v1-apm-span` |
| QueryLocator.kind | literal `query` | R | — | Union discriminator | `query` |
| QueryLocator.query_id | Id (`query`) | R | — | Hash of query template/version/parameters/source cutoff | `query_<hash>` |
| QueryLocator.index_alias | string, 1..255 | R | — | Trusted source alias | `aiops-logs` |
| QueryParameters.service_ids | list[Id (`svc`)], 1..20 | R | — | Exact allowed scope | `[svc_<hash>]` |
| QueryParameters.window | TimeRange | R | — | Bounded source interval | R |
| QueryParameters.trace_id | TraceId | N | — | Optional trace filter | null |
| QueryParameters.severity_min | enum `DEBUG`, `INFO`, `WARN`, `ERROR`, `FATAL` | N | — | Log severity lower bound | `ERROR` |
| QueryParameters.feature | Feature | N | — | Feature filter | `error_rate` |
| QueryParameters.features | list[Feature],max2,unique | R | — | Multi-feature metric selection; empty when not applicable | `[latency_p95_ms,error_rate]` |
| QueryParameters.incident_id | Id (`incident`) | N | — | Exact incident lookup scope | null |
| QueryParameters.bundle_id | Id (`bundle`) | N | — | Pinned evidence bundle if applicable | null |
| QueryParameters.detector_id | string,1..256 | N | — | Detector-result filter if applicable | null |
| QueryParameters.document_id | string,1..512 | N | — | Direct document lookup; source index comes from locator/template | null |
| QueryParameters.max_spans | int1..200 | N | spans | Trace reconstruction cap if applicable | 100 |
| QueryParameters.text_contains | string, max 256 | N | — | Literal text search, not a query language | `timeout` |
| QueryParameters.status | enum `error`, `ok` | N | — | Span/trace status filter | `error` |
| QueryParameters.min_duration_ms | float >= 0 | N | ms | Duration lower bound | 500 |
| QueryParameters.limit | int 1..200 | R | items | Requested bounded count | 20 |
| QueryParameters.direction | enum `upstream`, `downstream`, `both` | N | — | Dependency traversal direction | null |
| QueryParameters.include_native | bool | R | — | Whether allowlisted native metrics were included | false |
| QueryParameters.cursor_digest | string, 64 lowercase hex | N | — | Hash of pagination cursor; raw signed token not stored | null |
| Provenance.query_id | Id (`query`) | R | — | Stable query identity | `query_<hash>` |
| Provenance.template_id | Label | R | — | Host-owned template, including direct document lookup | `logs-by-service` |
| Provenance.template_version | Version | R | — | Query behavior version | `1.0.0` |
| Provenance.parameters | QueryParameters | R | — | Typed effective filters, including defaults | See above |
| Provenance.retrieved_at | UtcTime | R | — | Retrieval time | T |
| Provenance.source_cutoff | UtcTime | R | — | Snapshot/visibility cutoff used by query | T |
| Provenance.returned_count | int >=0 | R | items | Returned source items | 20 |
| Provenance.matched_count | int >=0 | N | items | Exact total if known; null if not counted | 24 |
| Provenance.truncated | bool | R | — | More matching records were omitted | true |

`SourceLocator = DocumentLocator | TraceLocator | QueryLocator`, discriminated by `kind`.

## Typed evidence snapshots

`EvidenceSnapshot` is a discriminated union on `kind`; types cannot contain arbitrary JSON. Fields marked inherited reference the complete schema above, without changing it.

| Variant | Required fields / types / units / semantics / examples | Nullable fields |
|---|---|---|
| AnomalySnapshot | `kind="anomaly_result"`; `anomaly: Anomaly` (normalized observed result; example above) | None |
| MetricBucketSnapshot | `kind="metric_bucket"`; `bucket: ServiceMetricBucket` (frozen feature record; example above) | None |
| LogSnapshot | `kind="log_record"`; `event_time: UtcTime=T`; `severity: DEBUG/INFO/WARN/ERROR/FATAL="ERROR"`; `body: str<=4096="Payment request failed"`; `service: ServiceKey=K` | `trace_id: TraceId=null`; `span_id: SpanId=null`; `error_type: str<=128="TimeoutError"` |
| SpanSnapshot | `kind="span"`; `trace_id: TraceId` and `span_id: SpanId` (examples above); `service: ServiceKey=K`; `name: str<=256="POST /payments"`; `span_kind: SERVER/CLIENT/INTERNAL/PRODUCER/CONSUMER="SERVER"`; `start_time: UtcTime=T`; `end_time: UtcTime=T+0.2s`; `duration_ms: float>=0=200`; `status: UNSET/OK/ERROR="ERROR"` | `parent_span_id: SpanId=null`; `http_status_code: int 100..599=503`; `http_route: str<=256="/payments"` |
| TraceSnapshot | `kind="trace"`; `trace_id: TraceId`; `window: TimeRange=R`; `services: list[ServiceKey],1..20=[K]`; `spans: list[SpanSnapshot],1..200`; `root_present: bool=true`; `truncated: bool=false`; `missing_parent_count: int>=0=0` | `observed_span_count: int>=0=12` (null if exact count unavailable) |
| ErrorGroupSnapshot | `kind="error_group"`; `fingerprint: Id(errorgroup)`; `service: ServiceKey=K`; `window: TimeRange=R`; `error_type: str<=128="TimeoutError"`; `message_template: str<=512="upstream timeout"`; `count: int>=1=7`; `sample_evidence_ids: list[Id(ev)],1..3` | None |
| DependencySnapshot | `kind="dependency_edge"`; `edge: DependencyEdge` (schema below) | None |
| NativeMetricSnapshot | `kind="native_metric"`; `service: ServiceKey=K`; `name: str<=128="process.cpu.utilization"`; `unit: str<=32="1"`; `window: TimeRange=R`; `metric_type: gauge/sum/histogram="gauge"`; `temporality: unspecified/delta/cumulative="unspecified"`; `attribute_labels: list[MetricLabel],max16=[]`; `value: NativeMetricValue` | None |

All fields listed in nullable column are **N**. Fixed discriminators and variant fields are **R**. MetricLabel: `key: str<=64` R (allowlisted dimension, example `http.request.method`); `value: str<=128` R (example `POST`). No additional label names are accepted without registry approval.

NativeMetricValue is discriminated: `kind="scalar"`, R `value: finite float` (native metric unit, example 0.2); or `kind="histogram"`, R `count:int>=0` (observations, example 100), N `sum:finite float` (native unit, example 10.2), R `bounds:list[finite float],max64` (strictly increasing, example [0.1,0.5]), R `counts:list[int>=0],max65` (length=bounds+1, sum=count, example [20,70,10]). Histogram expansion must be bounded; unsupported exponential layouts return partial rather than invented scalar values.

## EvidenceItem and EvidenceBundle

| Model.field | Type | Presence | Units | Semantics | Example |
|---|---|---|---|---|---|
| EvidenceItem.evidence_id | Id (`ev`) | R | — | Hash of type, source identity, snapshot content hash, redaction version | `ev_<hash>` |
| EvidenceItem.evidence_type | enum of EvidenceSnapshot kinds | R | — | Must match snapshot discriminator | `span` |
| EvidenceItem.source | SourceLocator | R | — | Source reference for audit | DocumentLocator example |
| EvidenceItem.service | ServiceKey | R | — | Principal subject; other trace services in snapshot | K |
| EvidenceItem.window | TimeRange | R | — | Subject event range; instantaneous events use [time,time+1ns) | R |
| EvidenceItem.summary | string, 1..512 | R | — | Readable, redacted factual description | `Payment span returned HTTP 503` |
| EvidenceItem.quality_status | QualityStatus | R | — | Completeness of this evidence only | `complete` |
| EvidenceItem.quality_reasons | list[ReasonCode],max16 | R | — | Why evidence is incomplete | `[]` |
| EvidenceItem.redaction_status | enum `checked_clear`, `redacted` | R | — | Unchecked evidence is rejected | `redacted` |
| EvidenceItem.redaction_version | Version | R | — | Redaction policy | `1.0.0` |
| EvidenceItem.provenance | Provenance | R | — | Typed retrieval details | See above |
| EvidenceItem.snapshot | EvidenceSnapshot | R | — | Bounded immutable source view | SpanSnapshot |
| EvidenceItem.content_sha256 | string,64 hex | R | — | Hash of canonical redacted snapshot bytes | `<64 hex>` |
| EvidenceItem.stored_bytes | int 1..262144 | R | bytes | Actual compact UTF-8 serialized item length; iterate this field until encoded length is stable, then validate cap | 1450 |
| EvidenceItem.created_at | UtcTime | R | — | Persistence time | T |
| EvidenceBundle.bundle_id | Id (`bundle`) | R | — | Incident ID + evidence revision + content digest | `bundle_<hash>` |
| EvidenceBundle.incident_id | Id (`incident`) | R | — | Owning episode | `incident_<hash>` |
| EvidenceBundle.version | int>=1 | R | revision | Monotonic committed incident evidence revision | 1 |
| EvidenceBundle.window | TimeRange | R | — | Actual collection interval | R |
| EvidenceBundle.evidence_ids | list[Id (`ev`)],1..300,unique | R | — | Ordered selected immutable items | `[ev_<hash>]` |
| EvidenceBundle.quality_status | QualityStatus | R | — | Bundle-level completeness | `partial` |
| EvidenceBundle.quality_reasons | list[ReasonCode],max16 | R | — | Includes truncation/query failures | `[truncated]` |
| EvidenceBundle.total_bytes | int 1..2097152 | R | bytes | Sum of serialized referenced item sizes | 180000 |
| EvidenceBundle.created_at | UtcTime | R | — | Commit time | T |

## InvestigationJob

| Field | Type | Presence | Units | Semantics | Example |
|---|---|---|---|---|---|
| investigation_id | Id (`inv`) | R | — | Deterministic request key; processing.md defines inputs | `inv_<hash>` |
| incident_id | Id (`incident`) | R | — | Authorized incident | `incident_<hash>` |
| evidence_bundle_id | Id (`bundle`) | R | — | Immutable initial bundle | `bundle_<hash>` |
| evidence_version | int>=1 | R | revision | Pinned bundle version | 1 |
| trigger | enum `automatic`, `user` | R | — | Source of request | `automatic` |
| requested_by | string,1..128 | R | — | Authenticated principal or literal `system`; never client-trusted | `system` |
| idempotency_key_hash | string,64 hex | R | — | Hash of request idempotency scope/key, not a secret | `<64 hex>` |
| state | InvestigationState | R | — | Job lifecycle | `queued` |
| attempt_count | int 0..3 | R | attempts | Incremented atomically on claim | 0 |
| attempt_id | Uuid | N | — | Current claim token | null |
| lease_owner | string,1..128 | N | — | Worker incarnation ID | null |
| lease_expires_at | UtcTime | N | — | Claim expiry; stale workers cannot commit | null |
| next_attempt_at | UtcTime | N | — | Retry eligibility; null when terminal/running | T |
| created_at | UtcTime | R | — | Persisted before 202 response | T |
| started_at | UtcTime | N | — | First claim time | null |
| finished_at | UtcTime | N | — | Terminal time | null |
| updated_at | UtcTime | R | — | Last job update | T |
| provider_id | Label | R | — | Configured adapter, not secret | `configured-provider` |
| model_id | string,1..128 | R | — | Requested provider model identifier | `configured-model` |
| prompt_version | Version | R | — | Prompt contract | `1.0.0` |
| tool_contract_version | Version | R | — | Tool registry version | `1.0.0` |
| additional_evidence_ids | list[Id (`ev`)],max100,unique | R | — | Tool-acquired persisted evidence, outside pinned initial bundle | `[]` |
| tool_calls_used | int 0..8 | R | calls | Executed across this job's current attempt | 0 |
| input_tokens | int>=0 | N | tokens | Provider-reported total across attempts; null if unavailable | 1200 |
| output_tokens | int>=0 | N | tokens | Provider-reported total across attempts | 400 |
| cost_usd | float>=0 | N | USD | Sum if known from configured rates; never fabricate | null |
| last_error | Failure | N | — | Sanitized structured failure | null |
| report | InvestigationReport | N | — | Validated final/partial report; no hidden chain-of-thought | null |

Failure: **R** `code: enum(timeout,unavailable,rate_limited,invalid_output,invalid_citation,forbidden,not_found,invalid_argument,source_expired,budget_exhausted,storage_error,unsupported_metric)` (example `timeout`); **R** `message:str<=512` (example `Provider deadline exceeded`); **R** `retryable:bool` (example true). Value object, no schema_version.

## InvestigationReport and claims

| Model.field | Type | Presence | Units | Semantics | Example |
|---|---|---|---|---|---|
| EvidenceClaim.statement | string,1..1000 | R | — | One factual interpretation/hypothesis | `Payment latency may originate in its inventory call` |
| EvidenceClaim.evidence_ids | list[Id (`ev`)],1..8 | R | — | Existing relevant evidence supporting that statement | `[ev_<hash>]` |
| SuggestedAction.instruction | string,1..512 | R | — | Human next check/remediation suggestion | `Check inventory saturation during this interval` |
| SuggestedAction.rationale | EvidenceClaim | R | — | Why suggestion follows from observations | Claim example |
| SuggestedAction.executed | literal false | R | — | Actions are never executed in beta | false |
| InvestigationReport.summary | EvidenceClaim | R | — | Short overall evidence-backed conclusion | Claim example |
| InvestigationReport.affected_services | list[ServiceKey],1..20 | R | — | Authorized observed services | `[K]` |
| InvestigationReport.affected_service_claims | list[EvidenceClaim],1..20 | R | — | Statements name service IDs and support affected list | Claim examples |
| InvestigationReport.suspected_root_service | ServiceKey | N | — | Hypothesis candidate; nullable | null |
| InvestigationReport.root_service_claim | EvidenceClaim | N | — | Required iff candidate non-null | null |
| InvestigationReport.primary_hypothesis | EvidenceClaim | N | — | Null when evidence cannot support a hypothesis | null |
| InvestigationReport.supporting_evidence_ids | list[Id (`ev`)],1..100,unique | R | — | Union of supporting references | `[ev_<hash>]` |
| InvestigationReport.contradicting_evidence | list[EvidenceClaim],max5 | R | — | Evidence against main interpretation | `[]` |
| InvestigationReport.alternative_explanations | list[EvidenceClaim],max3 | R | — | Plausible alternatives tied to actual observations | `[]` |
| InvestigationReport.confidence | Confidence | R | — | Wording, not probability | `low` |
| InvestigationReport.confidence_rationale | string,1..1000 | R | — | Relates confidence to cited findings and missing evidence | `No downstream error span was available` |
| InvestigationReport.recommended_next_checks | list[SuggestedAction],max5 | R | — | Human investigation suggestions | `[]` |
| InvestigationReport.suggested_remediation | list[SuggestedAction],max3 | R | — | Conditional unexecuted suggestions | `[]` |
| InvestigationReport.missing_evidence | list[string<=256],max10 | R | — | Explicit information not obtained | `[Inventory process metrics unavailable]` |
| InvestigationReport.limitations | list[string<=256],max10 | R | — | Sampling/truncation/time/provider limitations | `[Trace evidence is incomplete]` |
| InvestigationReport.completion_status | enum `complete`, `partial`, `insufficient_evidence` | R | — | A successful job can yield any of these | `insufficient_evidence` |
| InvestigationReport.generated_at | UtcTime | R | — | Host-stamped report time | T |

Missing-evidence statements are not fabricated observations. An insufficient-evidence summary cites the initial anomaly/bucket and states that it does not identify a cause. `confidence_rationale`, limitations, and actions cannot introduce uncited new material claims; the validator/prompt enforce this constraint. Referential validation cannot prove a hypothesis true.

## ServiceHealth and DependencyEdge

| Model.field | Type | Presence | Units | Semantics | Example |
|---|---|---|---|---|---|
| ServiceHealth.service | ServiceKey | R | — | Subject service | K |
| ServiceHealth.state | enum `healthy`, `degraded`, `unhealthy`, `unknown` | R | — | Deterministic projection specified in processing.md | `degraded` |
| ServiceHealth.reason | string,1..512 | R | — | Human explanation | `Active latency incident; current telemetry fresh` |
| ServiceHealth.assessed_at | UtcTime | R | — | Evaluation time | T |
| ServiceHealth.latest_bucket_end | UtcTime | N | — | Latest finalized minute available | T |
| ServiceHealth.telemetry_age_seconds | float>=0 | N | seconds | assessed_at minus latest raw ingestion time, clamped at 0 | 4.2 |
| ServiceHealth.active_incident_ids | list[Id (`incident`)],max100 | R | — | Open/recovering episodes | `[incident_<hash>]` |
| ServiceHealth.quality_status | QualityStatus | R | — | Quality of health inference | `complete` |
| ServiceHealth.quality_reasons | list[ReasonCode],max16 | R | — | Unknown/stale explanation | `[]` |
| DependencyEdge.edge_id | Id (`edge`) | R | — | Hash of source/target service IDs, observation window, adapter version | `edge_<hash>` |
| DependencyEdge.source_service | ServiceKey | R | — | Caller | `order-service` ServiceKey |
| DependencyEdge.target_service | ServiceKey | R | — | Callee; must share namespace/environment in beta | K |
| DependencyEdge.window | TimeRange | R | — | Observation interval, not validity forever | R |
| DependencyEdge.observed_trace_count | int>=1 | N | traces | Exact distinct support count if available from source; null otherwise | 12 |
| DependencyEdge.sample_trace_ids | list[TraceId],max5 | R | — | Actual supporting traces when available | `[]` |
| DependencyEdge.source | DocumentLocator or QueryLocator | R | — | Native map or bounded trace query reference | Locator example |
| DependencyEdge.observed_at | UtcTime | R | — | Retrieval/observation time | T |
| DependencyEdge.quality_status | QualityStatus | R | — | Map may be lagging or partial | `partial` |
| DependencyEdge.quality_reasons | list[ReasonCode],max16 | R | — | Known limitations | `[query_partial]` |

## WorkerCursor and WorkerState

Cursor is a discriminated union, not a generic JSON checkpoint. All fields below are required except **N** fields.

| Model.field | Type | Presence | Units | Semantics | Example |
| ResultCursor.kind | literal `anomaly_results` | R | — | Cursor discriminator | `anomaly_results` |
| ResultCursor.committed_through | UtcTime | R | — | Last fully processed execution-time boundary | T |
| ResultCursor.tie_index | string,1..255 | N | — | Last source physical index at boundary | `opensearch-ad-plugin-result-aiops-history-...` |
| ResultCursor.tie_document_id | string,1..512 | N | — | Last stable source ID at boundary | `native-result-id` |
| ResultCursor.last_reconciled_at | UtcTime | N | — | Last completed retained-history reconciliation | T |
| AggregationCursor.kind | literal `aggregation` | R | — | Cursor discriminator | `aggregation` |
| AggregationCursor.service_id | Id (`svc`) | R | — | Progress is per registered service | `svc_<hash>` |
| AggregationCursor.finalized_through | UtcTime | R | — | End of latest sequential finalized/explicit insufficient minute | T |
| AggregationCursor.aggregation_version | Version | R | — | Feature contract version | `1.0.0` |
| InvestigationCursor.kind | literal `investigation_scan` | R | — | Progress is advisory; each scan also finds all due/expired jobs | `investigation_scan` |
| InvestigationCursor.last_scan_at | UtcTime | R | — | Scan completion | T |
| WorkerState.worker_state_id | Id (`worker`) | R | — | Worker role + partition identifier | `worker_<hash>` |
| WorkerState.role | enum `aggregation`, `incident`, `investigation` | R | — | Process responsibility | `incident` |
| WorkerState.partition | string,1..128 | R | — | `singleton` initially except per-service aggregation cursor | `singleton` |
| WorkerState.cursor | WorkerCursor | R | — | Union matching role | ResultCursor example |
| WorkerState.owner_id | string,1..128 | R | — | Current process incarnation, for diagnosis | `incident-worker-7c932` |
| WorkerState.heartbeat_at | UtcTime | R | — | Last persisted liveness signal | T |
| WorkerState.status | enum `starting`, `running`, `degraded`, `stopped` | R | — | Worker health, not detector status | `running` |
| WorkerState.last_error | Failure | N | — | Last recoverable/fatal worker failure | null |
| WorkerState.updated_at | UtcTime | R | — | CAS-protected update timestamp | T |

WorkerState does not provide cross-document fencing. v1 permits one incident/aggregation writer process; investigation leases fence updates on their own job documents. OpenSearch `_seq_no`/`_primary_term` are repository concurrency tokens, not business fields.
