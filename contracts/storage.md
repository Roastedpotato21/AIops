# OpenSearch storage contracts v1

Companion to [domain](domain.md), [processing](processing.md), [agent](agent.md), and [API](api.md). These are mapping/ownership specifications, not executable index templates. Phase 1 establishes template/bootstrap layout and probe mappings only; later indexes are implemented by their owning phase.

## Mapping rules

Application-owned templates: `dynamic: strict`, explicit mapping, one primary shard, zero replicas for the single-node beta. Cluster scaling changes replica/shard policy explicitly. `_source` enabled. ID/type/version/enums are keyword, not analyzed text. Disable coercion where meaningful; API/domain validation happens before indexing.

The following recursive rules resolve every field in the typed domain tables unless an explicit exception below overrides them:

| Declared domain type / field purpose | OpenSearch type | Notes |
|---|---|---|
| Id, Uuid, TraceId, SpanId, Label, Version, enum, source index/document ID, hashes, route, model/provider IDs | keyword | Bounded lengths as in domain; exact search/filter |
| UtcTime for worker/job/incident/bucket/provenance times | date, format strict_date_optional_time_nanos | Date stores milliseconds; identity already hashes exact epoch-nanosecond input before serialization |
| Span/event start/end times requiring sub-ms reconstruction | date_nanos | Native trace template may already choose its own representation; adapter preserves original precision |
| TimeRange | object, dynamic strict | start/end mapped per owning record; bucket/incident dates use date, span/log event dates use date_nanos |
| Counts/byte lengths/token counts | long | Nonnegative validated by application |
| Milliseconds, ratios, costs, other finite measurement values | double | No integer truncation; null allowed per domain |
| Bool / literal bool | boolean | No string coercion |
| Human summary/body/reason/statement/instruction/template/limitation/message | text | No automatic keyword multifield on unbounded human text |
| Bounded arbitrary opaque identifiers such as instance_id/provider_request_id | keyword | Never used as authorization source without scope checks |
| Single fixed-shape nested model | object, dynamic strict | Apply recursive rules |
| Scalar arrays | Array of declared scalar mapping | No separate array type |
| Arrays of objects queried with same-element predicates | nested | Explicit list below; queries must use nested paths |
| Arrays of objects for display only | object with enabled=false | Retain validated source without indexed subfields |

Indexed nested arrays: Incident.affected_services and related_incidents; TraceSnapshot.services only if materialized outside unindexed snapshot; ServiceKey lists used for query scope; MetricLabel pairs when explicitly indexed. Do not use ordinary flattened object arrays for predicates that must match namespace/environment/service on the same member. `service` (single ServiceKey) is an object with service_id/namespace/environment/name keyword. Native Data Prepper mappings are an exception owned by that product, not rewritten by these defaults.

Unindexed fixed snapshots: EvidenceItem.snapshot, Provenance.parameters, InvestigationReport and tool_executions. These remain strictly typed and byte-bounded in application validation even though OpenSearch doesn't index children. IDs/state/time fields required for querying stay separately indexed. Disabled mapping does not permit arbitrary content or secrets.

Use `index:false` for provider_request_id and safe operational diagnostics not queried if otherwise a keyword; use `enabled:false` only on object fields. Map ReasonCode arrays as keyword. No wildcard dynamic templates that create a field per attribute key. Raw attributes are allowlisted into fixed fields or retained in a bounded unindexed object with a typed AttributeValue union (string<=256, finite number, boolean); max32 entries, allowlisted keys only.

## Index/alias ownership and retention candidates

`-v1` aliases express mapping generation. Physical application indexes normally use `alias-000001` (single backing index for mutable records). Read aliases, write behavior, and retention must not be conflated. No user or model chooses a physical index.

| Logical family / aliases | Required indexed fields and exceptions | Writer / reader boundary | Retention candidate |
|---|---|---|---|
| `aiops-logs-*`; read `aiops-logs` | event_time date_nanos, ingested_at date, service keyword object, trace_id/span_id keyword, severity keyword, body text, error_type keyword, redaction_version keyword; raw allowed attrs unindexed | Data Prepper append/deterministic-ID path; API/workers read | 7 days, deterministic UTC day indexes; reject expired replay |
| `aiops-metrics-raw-*`; read `aiops-metrics-raw` | metric name/unit/type/temporality keyword; service object; start_time/end_time date_nanos; scalar value/sum double; count long; explicit bounds double[], counts long[]; attribute labels nested fixed key/value if queried, otherwise unindexed | Data Prepper; read-only corroboration adapters | 7 days, UTC day indexes |
| Data Prepper trace indexes; native read alias/pattern | Preserve native traceId/spanId/parentSpanId/serviceName/time/duration/status/attribute mappings. Adapter manifest records actual verified field paths and units for IDs, kind, HTTP status/route, environment, start/end, ingestion time | Data Prepper only; trace adapter reads | 7 days; compatible deterministic end-date routing for idempotency, see processing |
| Data Prepper service-map indexes; native read alias | Preserve native template and processor fields. Manifest records source/target identity and observed-window mapping | Data Prepper only; topology adapter reads | 7 days or native supported equivalent; document native rollover behavior |
| `aiops-service-metrics-v1` | All ServiceMetricBucket fields per recursive rules; bucket_time/date, service.service_id keyword, finalized_at date, eligible_for_detection boolean, feature values double, counts long | Aggregation worker; AD source read and API/incident/tool reads | 30 days; initially single mutable backing index; delete old completed records by window.end |
| `opensearch-ad-plugin-result-aiops-v1` | Plugin-owned result template; detector_id keyword, native data/execution times as supplied, anomaly_grade/confidence numeric; feature_data/entity retain native structures | AD plugin; result adapter via supported API or scoped custom-index reads | 30 days candidate, actual plugin rollover/retention settings verified |
| `aiops-anomalies-v1` | Anomaly fields plus ProcessingEnvelope below; source locators typed object, service/feature keyword, windows/execution/observed dates, grade/confidence/value double | Incident worker writes; API/incident evidence reads | 30 days after processed; unprocessed/failed backlog not silently expired |
| `aiops-incidents-v1` | Incident fields; affected_services and related_incidents nested; baseline fixed object; recent IDs keyword[]; state/severity keyword; SchedulingReservation unindexed, timeline_events unindexed | Incident engine writes lifecycle; scheduler CAS-updates only reserved job/pointer fields; API reads | Resolved 90 days after resolved_at; active episodes not automatically deleted |
| `aiops-evidence-v1` | Discriminated EvidenceItem/Bundle documents; record_kind keyword; evidence/bundle/incident IDs keyword; evidence_type keyword; window date_nanos; summary text; quality/redaction keyword; provenance fixed object, parameters disabled; snapshot disabled; bundle references keyword[] | Evidence collector / investigation host runner; read tools/API scoped | Follow owning incident/jobs, 90-day candidate; do not expire references of retained reports/bundles |
| `aiops-investigations-v1` | InvestigationJob fields; state/incident/bundle/attempt IDs keyword; due/lease/times date; attempts/tokens/counts long; cost double; report disabled; executions disabled; references keyword[]; idempotency/body digests keyword | API scheduler creates; investigation runner claims/completes; API reads safe view | Terminal jobs 90 days after finish; active jobs retained |
| `aiops-worker-state-v1` | Discriminated records below; role/partition/record_kind keyword, progress/cursor times date, registry mapping fields keyword, health boolean/enums; fixed error object | Respective worker/bootstrap/provisioning tools only; internal diagnostics reads | No automatic deletion of active progress/registry; stale completed evidence tasks30d |

Raw log/metric physical indexes do not have to match canonical API field spelling if the pinned Data Prepper format supplies different fields. A committed `telemetry-field-map` manifest must map every required canonical field above to actual native paths and units, tested with probe fixtures. New wrapper fields require explicit mapping; do not silently rename native trace mappings. Logical query adapters shield callers from this difference.

Initial app-owned mutable indexes do **not** roll over. Global ID uniqueness does not hold across rollover backing indexes. If later volumes require rollover, add a tested identity/partition strategy before changing it. Raw time-partition indexes use deterministic event-date routing; native AD results retain plugin behavior and source physical IDs in our dedup key.

## Exact persistence-only schema extensions

These are repository models extending domain records, not arbitrary metadata. All fields below R unless N. Times use UtcTime, IDs/types follow domain.md. Fields named O have explicit defaults at creation. Examples are illustrative.

| Model | Fields, meanings, and examples |
|---|---|
| ProcessingEnvelope (on Anomaly) | `processing_state: pending/assigned/processed/failed` R (current durable stage;pending); `disposition:undecided/non_anomalous/opened/attached/suppressed_quality/historical_unassigned` R (decision;undecided); `decision_reason:str<=512` N (why not opened;null); `incident_id:Id(incident)` N (assigned episode;null); `policy_version:Version` R (1.0.0); `processed_at:UtcTime` N (null); `last_error:Failure` N (null). Stored as fixed object `processing`. Normal non-incident results have null incident_id and processed state. Historical_unassigned results remain searchable and appear in worker degradation diagnostics; reconciliation retries them if missing retained evidence becomes available. |
| Incident persistence additions | `resolution_bucket_end:UtcTime` N (latest recovery end used for historical assignment;null); `peak_severity:IncidentSeverity` R (maximum observed impact;medium); `timeline_events:list[TimelineEntry],max100` R ([]); `scheduling_reservation:SchedulingReservation` N (null); `automatic_job_count:int0..5` R (0); `user_job_count:int0..5` R (0); `last_automatic_job_at:UtcTime` N (null); `last_user_job_at:UtcTime` N (null); `last_evidence_refresh_at:UtcTime` N (null). |
| SchedulingReservation | `investigation_id:Id(inv)` R; `trigger:automatic/user` R; `principal_id:str1..128` R; `idempotency_key_hash:64hex` R; `request_body_sha256:64hex` R; `requested_evidence_version:int>=1` N (null means latest-selection request); `resolved_evidence_bundle_id:Id(bundle)` R; `resolved_evidence_version:int>=1` R; `reserved_at:UtcTime` R; `provider_id:Label` R; `model_id:str<=128` R; `prompt_version:Version` R; `tool_contract_version:Version` R. Example values are corresponding Job fields. |
| Investigation persistence additions | `request_body_sha256:64hex` R (canonical submitted body digest); `requested_evidence_version:int>=1` N (request selection mode); `tool_executions:list[ToolExecution],max24` R ([]); `cost_limit_usd:float>0` N (0.50); `additional_evidence_bytes:int0..1048576` R (0). |
| Evidence document discriminator | `record_kind: evidence_item/evidence_bundle` R. Item variant extends EvidenceItem; bundle variant extends EvidenceBundle. `owner_incident_id:Id(incident)` R on both; evidence IDs remain source/content based. Shared items can be referenced by multiple incidents; ownership here records first creator, retention uses reference reachability not owner alone. |

Scheduling algorithm: resolve and validate bundle → CAS incident to reserve exact job ID and increment the relevant quota once → create/get deterministic job from reservation → CAS pointer/latest ID and clear reservation. Other concurrent callers see reservation and return same job for the same request (after reconstructing it if needed) or409 for a different request. A crash after reserve is repaired from the complete reservation; do not expire a reservation and spend quota again. Before reserving, look up deterministic job ID for idempotent retries and inspect any latest nonterminal job. Incident worker updates must read-modify-CAS preserving scheduler fields; no full blind overwrite.

The per-incident reservation prevents duplicate active job creation without adding another datastore. It does not imply global transactions or a cluster-wide lock.

Worker-state index is a union on record_kind:

| Variant | Exact fields (all R unless N), units/semantics, example |
|---|---|
| worker_cursor | Domain WorkerState plus `record_kind="worker_cursor"`; examples in domain |
| detector_registration | `schema_version:Version`; `record_kind="detector_registration"`; `registration_id:Id(detreg)` hash(service_id,feature,config_version); `service:ServiceKey`; `feature:Feature`; `native_detector_id:str<=256` N; `detector_name:str<=256`; `config_version:Version`; `aggregation_version:Version`; `config_sha256:64hex`; `state:planned/active/retired/failed`; `activated_at:UtcTime` N; `retired_at:UtcTime` N; `updated_at:UtcTime`; `last_error:Failure` N. Example: K,error_rate,1.0.0,active. |
| bootstrap | `schema_version:Version`; `record_kind="bootstrap"`; `bootstrap_id:literal "platform-bootstrap-v1"`; `release_id:str1..128`; `contract_version:Version`; `state:pending/ready/failed`; `completed_at:UtcTime` N; `last_error:Failure` N. Example release `phase1-probe`, ready. No secrets or tokens. |
| evidence_task | `schema_version:Version`; `record_kind="evidence_task"`; `task_id:Id(evtask)` hash(incident_id,trigger_anomaly_id,revision); `incident_id:Id(incident)`; `trigger_anomaly_id:Id(anomaly)`; `target_version:int>=1`; `state:pending/running/succeeded/failed`; `attempt_count:int0..3`; `next_attempt_at:UtcTime` N; `bundle_id:Id(bundle)` N; `created_at:UtcTime`; `updated_at:UtcTime`; `last_error:Failure` N. Example pending,attempt_count0. Singleton incident worker owns these tasks. |

Evidence tasks retry up to3 times with30s/120s delays; failed collection marks incident evidence_status failed/partial as appropriate. An operator-authorized later retry or new material evidence can schedule a new task revision. Startup reconciliation finds missing tasks from processed anomaly/incident state.

## Privileges and ownership

| Principal | Allowed access |
|---|---|
| Bootstrap/admin | Create templates/aliases/roles and bootstrap marker; detector provisioning only in Phase5+ |
| Data Prepper | Write approved telemetry indexes; required template initialization only if explicitly delegated |
| Detector runtime | Read feature alias; plugin-required write/manage access to its result/model state, verified for pinned security plugin |
| Aggregation/incident worker | Read telemetry/results; write buckets/anomalies/incidents/evidence/its state; no infrastructure control |
| Tool reader | Read only authorized evidence/telemetry/buckets/incident views; no plugin admin or write rights |
| Investigation host | Read inputs; write own job records/evidence; no telemetry mutation |
| API | Read product records; bounded investigation scheduling writes; no general-purpose search endpoint |
| Browser | FastAPI only |

Separate component credentials. The first scaffold may use a clearly isolated bootstrap identity while roles are initialized; completion must identify whether runtime least-privilege roles are active. Never expose bootstrap/admin credentials to frontend or LLM context. OpenSearch security and verified TLS are required for deployment; local development exceptions must be explicit and loopback/private-network scoped.

## Consistency, lifecycle, and budgets

- Use `_create` for immutable IDs and `_seq_no`/`_primary_term` conditional updates for mutable records. Conflict means reread/reconcile, not blind overwrite.
- Search is near-real-time. Use real-time ID retrieval for persisted investigation POST verification. Poll-based scans tolerate refresh delay; don't refresh every telemetry document.
- Lease fences apply to a single InvestigationJob document. There are no cross-document atomic commits; reconcile partial writes explicitly.
- Max item256KiB, bundle referenced bytes2MiB, job512KiB, incident256KiB. If domain arrays/text limits still exceed serialized document limit, omit optional history and mark truncation; never omit required identity/state or silently lose current job claims.
- Raw retention uses date-index deletion/ISM tested with the native templates. Mutable application retention uses bounded scheduled deletion of eligible terminal/old records, not age-based deletion of an entire mixed active index.
- Evidence deletion is reference-aware: never remove items referenced by a retained bundle or job. Unreferenced orphan items may be removed after24h. At five auto+five user jobs and 20 bundles, evidence growth per incident is bounded; active incident count still requires global disk/capacity monitoring.
- Native result retention and normalized processed-result retention share at least the recovery horizon. If a cursor predates retained history, mark degraded with an explicit unrecoverable interval, do not silently jump to now.
- Keep source references after raw expiry; snapshots remain readable with source_expired status when source drill-down fails.
- Disk alarms and query limits are mandatory before EC2 acceptance. Single-node volumes and snapshots do not make the service highly available.
