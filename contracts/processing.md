# Processing contracts v1

Normative companion to [domain.md](domain.md). All constants here belong to policy version `1.0.0`. They are implementation defaults to validate in the later owning phase, not claims of measured accuracy.

## 1. Normalized span and service registration boundary

Data Prepper owns physical trace mappings. A read adapter yields SpanSnapshot plus trusted ingestion time, service instance identity, and duplicate/validation diagnostics. Workers never depend on frontend DTO field spelling or dynamic trace attributes.

Registered service scope is an explicit list of ServiceKeys in non-secret configuration, initially order/payment/inventory in `demo-shop/development`. Observed unregistered services may appear in service queries, but no detector is provisioned implicitly. Service registration is not inferred from fault labels.

Required identity resource attributes: `service.namespace`, `service.name`, `service.instance.id`, and the pinned SDK's deployment-environment attribute. The ingestion adapter maps the verified semantic-convention spelling to `environment`; conflicting old/new spellings are rejected. Version drift must not merge environments.

## 2. Metric aggregation

### Identity and timing

- Logical group: ServiceKey, across all its instances. No route/status/trace ID is a detector category.
- Window: `[floor(end_time / 60s) * 60s, start + 60s)` in UTC. A span ending exactly on a minute belongs to the following minute.
- `bucket_id = H("bucket", [service_id, window_start_epoch_ns_string, aggregation_version])`.
- A bucket's `bucket_time` equals window.start. UTC source times and integer duration calculations avoid local-time/DST behavior.
- Worker runs every 10 seconds. It may update provisional buckets, but RCF reads finalized eligible buckets only.
- Finalization deadline: `window.end + 90s`. Use a consistent source snapshot at or after that deadline. Expected index visibility lag budget is another 10 seconds; Phase 4 measures it.
- Final feature publication uses deterministic create/CAS and `refresh=wait_for` where supported; retry publication safely. Cursor advances only after durable publication.
- RCF's 180-second delay is intended to exceed finalization plus visibility time even if its minute intervals are offset from UTC minutes. Phase 5 must verify the actual interval-boundary behavior.

### Inclusion/exclusion and errors

| Rule | Exact behavior |
|---|---|
| Span kind | Include `SERVER` only. Exclude CLIENT, INTERNAL, PRODUCER, CONSUMER. |
| Completeness | Require valid nonzero trace/span IDs, valid service identity, start/end present, end >= start. Zero-duration spans are allowed. |
| Protocol | Beta feature set covers HTTP server requests. Require HTTP status 100..599 or explicit span status ERROR. Non-HTTP SERVER spans are outside this version. |
| Time | Use completion/end time, not start or ingestion time. Reject known future clock skew >30s; mark affected bucket quality partial. |
| Health/admin | Exclude exact normalized route `/health`, `/healthz`, `/ready`, `/readyz`, `/live`, `/livez`, `/metrics`, `/docs`, `/openapi.json`; exclude route prefixes `/admin`, `/internal`, `/__faults` at segment boundaries. `/administer` is not excluded. |
| Route selection | Prefer instrumented route template. Otherwise use URL path with query removed solely for filtering. Never retain raw query parameters. Missing route/path is included only if it is a known business operation from configured server span names; otherwise mark invalid. |
| Errors | An included request is an error if HTTP status >=500 OR span status ERROR. HTTP 4xx alone is not an error. Count once even if both conditions hold. |
| Ambiguous status | No valid HTTP status and status not ERROR is invalid, not silently successful. Diagnostics count it and make the bucket partial. |
| Application retry | A genuine second server attempt has a new span ID and counts as a second server request; metric is attempts, not unique orders. |
| Ingestion retry | Same logical span must overwrite/reject the same source document, never create another counted span. |
| Fault labels | Never use injected fault flags, scenario names, or expected outcome labels in feature calculation, correlation, or agent input. |

### Span deduplication

Canonical span document ID is `H("span", [namespace, environment, trace_id, span_id])`. The service identity on duplicate spans must agree. Same ID and same redacted source content is a replay. Same ID with conflicting immutable content is a conflict: retain the first accepted semantic record and record a duplicate-conflict diagnostic. Do not let last-writer-wins silently alter duration/status.

Rollover creates a specific hazard: `_id` is unique only within a physical index. Route spans deterministically to a UTC **end-date** physical trace index, preserving the native trace index template and supported Data Prepper naming conventions. Replays must target that same date index. Late arrivals older than retention are rejected/recorded, not sent to the current write index. Adapter/probe must verify deterministic-ID and date-routing support in the selected Data Prepper release before Phase 4 acceptance. If unavailable, raise a concrete implementation blocker; do not claim alias-wide deduplication or change feature semantics silently.

Native managed service-map indexing may retain its own rollover scheme. A template-compatible trace routing adjustment is allowed; replacing native trace field mappings is not.

### Calculations and quality

| Field | Calculation |
|---|---|
| request_count | Number of unique included spans in group/window |
| source_count | Equal to request_count in v1; never raw exporter event count |
| error_count | Sum of the binary error predicate above |
| error_rate | error_count / request_count; null at zero requests |
| latency unit | `(end_time_ns - start_time_ns) / 1_000_000`; milliseconds |
| latency_mean_ms | Sum of included durations / request_count; null at zero |
| latency_p95_ms | OpenSearch percentile aggregation, TDigest compression 100, p95 over individual durations; approximate, never average of per-instance percentiles |
| invalid_span_count | Rejected candidate spans attributable to this service/minute; missing identity is a separate ingestion diagnostic |
| late_span_count | Distinct eligible spans discovered after frozen source cutoff |

Minimum sample count is **20 included requests per minute for both detectors**. Below 20, preserve observed numbers but set quality `insufficient`, reason `low_sample_count` (or `no_spans` when zero), eligibility false. This is a feature-reliability policy, not a statistical anomaly threshold.

Quality precedence:

1. `unknown`: source query unavailable or pipeline freshness/sampling configuration unknown; never substitute zeros for failed queries.
2. `partial`: shard/query partial result, known sampling <1, invalid candidates, duplicate conflict, known dropped telemetry, or clock skew. Eligibility false.
3. `insufficient`: query successful but fewer than 20 samples. Eligibility false.
4. `complete`: successful query, known full sampling, no detected integrity issue, >=20 samples. Eligibility true only once finalized.

For a successful empty query, store request_count/source_count/error_count=0, rates/latencies=null, insufficient quality. This is **zero observed completed spans**, not proof of zero actual traffic. Unknown queries create no invented zero bucket; retain retry state and expose the gap.

Native heartbeat metric and Collector/Data Prepper freshness diagnostics inform freshness. Metric emptiness alone cannot establish pipeline health. Raw application telemetry age >120s, or missing known sampling configuration, makes service health unknown.

### Late arrivals and immutable detector input

Recompute provisional values from the complete visible eligible span set, not incremental counter additions. Finalization freezes feature values and eligibility used by RCF. Later discoveries update only late_span_count and quality annotations; they never rewrite the detector feature value. Store that quality degradation as evidence and do not auto-resolve from affected minutes.

To avoid a changing filter retroactively removing prior input, the persisted `eligible_for_detection` is the **eligibility at finalization**. RCF filter uses it and finalized_at only, not mutable quality_status. Current-quality consumers also inspect current quality_status/late_span_count. Late-data diagnostics do not imply RCF rescored history. Reprocessing for a new aggregation version uses a new ID/version and new detector config, never overwrites the old series.

Maintain a sliding 10-minute late-arrival audit and a daily bounded reconciliation of the remaining retained span history. Expose detection/late-audit lag; finite retention limits what can be repaired.

## 3. RCF detector contract

| Setting | Latency | Error |
|---|---|---|
| Registry key | service_id + `latency_p95_ms` + config_version | service_id + `error_rate` + config_version |
| Name | `aiops-{service_id}-latency-v1` | `aiops-{service_id}-errors-v1` |
| Type | Single entity | Single entity |
| Source alias | `aiops-service-metrics-v1` | Same |
| Time field | `bucket_time` | Same |
| Feature | `latency_p95_ms`, `avg` aggregation | `error_rate`, `avg` aggregation |
| Scope filter | Exact service_id, aggregation_version=1.0.0, eligible_for_detection=true, finalized_at exists | Same |
| Interval | 1 minute | 1 minute |
| Window delay | 3 minutes | 3 minutes |
| Shingle | 8; record explicitly rather than depend on release default | 8 |
| Missing inputs | No zero fill, interpolation, or carry-forward | Same |
| Result alias | `opensearch-ad-plugin-result-aiops-v1` | Shared alias |
| Initial config_version | `1.0.0` | `1.0.0` |

One detector query interval must select exactly one finalized bucket; an offset minute can select a bucket whose full application interval differs from the detector's logical interval. Normalize by querying the exact detector filter and range and linking the selected bucket. Zero matches => insufficient; >1 => failed configuration invariant. Use the bucket's window for correlation. `avg` is identity with one record, not a license to average different minute p95s. Native feature_value must agree with that bucket within numeric tolerance.

No fixed anomaly score, grade cutoff such as 0.7, or confidence cutoff is introduced. A valid native grade **>0** means RCF classified an anomaly; grade=0 means normal. Null/NaN/invalid values are insufficient/failed, never zero. Detector confidence is preserved and shown, not converted to severity. The first version accepts anomalies in either direction; direction-specific suppression is a later evaluated policy revision.

State precedence: configured stopped → `stopped`; not yet started → `not_started`; native error/invalid mapping or invariant failure → `failed`; no eligible latest input → `insufficient_data`; plugin initializing/model unready → `warming_up`; otherwise successful recent scoring → `ready`. A stale status query is reported as partial/unavailable by the API, not guessed ready. Warm-up has no fixed promised duration; use native profile/status and observed successful scoring. A warm model can later return to insufficient_data.

Normalize native epoch milliseconds to UtcTime; persist source physical index and `_id`, detector configuration association, feature value, data window, execution times, native grade/confidence, and errors. Exclude historical-analysis task results from the live incident loop. A missing required timestamp/unknown detector becomes a recorded normalization error; never invent a service or time.

Configuration registry is a committed non-secret detector specification plus persisted native IDs/provisioning state in worker-state records. Registry changes create a new named detector/config revision; stop the old detector before activating the replacement. Keep its ID-to-version association for historical normalization. Do not mutate feature meaning under a running model. Phase 1 creates no detectors.

## 4. Persistent incident processing

### Polling and reconciliation

- Poll every 10s; page size 200, request timeout 5s. Read all registered detector results, including normal/error states.
- Start each poll from `committed_through - 5 minutes`, exclusive upper execution-time bound captured at poll start. Use supported stable source ordering/pagination; exact result API pagination support is a compatibility test in Phase 5.
- Do not sort blindly on `_id` if the release forbids it. The result repository must supply a tested stable tie strategy (for example PIT plus `_shard_doc`, with persistent source-ID dedup). Persist a time boundary only after all pages through that boundary have been processed. PIT cursors are per-scan, not restart checkpoints.
- Native execution time is the progress key; affected bucket time is the correlation key. Distinct delayed results with old data windows are still consumed.
- Re-scan from the last cursor on restart; perform startup and daily reconciliation of retained native result history to catch arrivals outside the five-minute overlap. Bound pages and yield between batches so live processing continues. Never claim recovery beyond retained history.
- Advance the cursor only after normalized results and their required incident/evidence scheduling effects are durable. A poison result is recorded with explicit failure and retried/backlogged; dropping it silently is forbidden.

### Deduplication and episode assignment

Anomaly result identity: `H("anomaly",[source.index,source.document_id])`. Add to normalized anomaly storage a processing envelope (storage.md) with incident assignment and processing state. Replays operate on that same document and resume unfinished effects.

Episode key: `[primary_service.service_id, feature, policy_version]`. v1 permits one active episode per key. Use one aggregation/incident process; do not run one scheduler in every API replica. A WorkerState heartbeat is not a distributed lock; no automatic multi-writer failover in beta.

Opening rules: registered live detector result, result_status anomalous, unique input bucket, finalized eligibility true, current quality complete, current late_span_count=0, and valid RCF grade >0. Confidence is retained but not used as a separate cutoff. A single eligible positive result opens the episode; no hidden persistence threshold.

Incident ID: `H("incident",[service_id,feature,opening_anomaly_id,policy_version])`. Preserve opening ID on replay. Primary service is the detector's service. Suspected root service initially remains null. Evidence collection failure does not delete/prevent the durable incident.

Assignment order for every new positive result:

1. If normalized result already has incident_id, use that assignment.
2. If its affected window overlaps a persisted episode's observed span from first_affected_at through its resolution evidence window, attach it there, even if the episode is resolved. Do not reopen merely because an old result arrived late; invalidate/reassess past recovery if contradictory.
3. Else if an active episode with that key exists and this is newer than its previous episode boundary, attach to active episode.
4. Else if an active episode exists but this is an older previously unassigned result, attach to that episode as late evidence, extend first_affected_at if needed, and reevaluate the baseline/recovery chronologically. Do not create a second active episode for that key. If moving the start would make a frozen baseline overlap the newly affected period, invalidate it and recapture only eligible pre-incident minutes.
5. Else create the deterministic new episode for this result. If its affected window predates the most recently resolved episode and is disjoint from it, first attempt historical recovery evaluation from retained later buckets. Only create a resolved historical episode if that recovery is provable. Otherwise retain the result as `historical_unassigned` with explicit missing-history diagnostics; do not represent an unprovable historical outage as a new present outage.

Choose among overlapping candidates by earliest detected_at then incident_id, and flag any overlap invariant violation. Persist assignment before advancing processing progress. Reconcile incident aggregates from assigned distinct anomaly documents rather than incrementing anomaly_count blindly. `first_affected_at=min(starts)`, `last_affected_at=max(ends)`, recent IDs capped at 100 sorted by affected time then ID. Repeated polls with unchanged evidence do not bump incident timestamps or evidence version.

Crash-safe sequence: persist normalized result pending → create/get episode deterministically → persist anomaly assignment → recompute incident summary → schedule evidence work → mark result processed → advance cursor. Any step may repeat. A created episode with an unassigned opening result is reconciled by opened_by_anomaly_id. There is no cross-index transaction.

### Correlation

Initial evidence window is `[first affected minute start - 5min, affected minute end + 2min)`, clipped at query time. Later collection focuses on the latest anomalous minute with the same padding. Maximum one query span is 30 minutes. Query primary service, then at most one observed dependency hop, up to 20 services total within the same namespace/environment.

Link episodes if they are within five minutes and either share an actual trace, have an observed dependency edge during the window, or represent two features on the same service. Record reason and evidence IDs. A dependency link means related candidates, not that both are affected; add a secondary affected service only with its own anomalous/error/latency evidence. Shared time alone does not link services. Never merge episodes in v1.

### Severity policy v1

Use the latest up to five finalized **complete** primary-service buckets since opening (also >=20 samples and no late-data annotation), independent of anomaly grade/confidence. Choose the highest matched class; freeze last severity when there is no fresh input and mark health/evidence stale. This is an explicit demo/beta impact policy, not a universal SLO.

| Severity | Exact input condition |
|---|---|
| critical | At least one considered bucket has error_rate >=0.20 |
| high | Otherwise error_rate >=0.05, OR latency_p95_ms >=3 * max(baseline latency median, 1ms) when baseline exists |
| medium | Otherwise any eligible RCF-positive episode (default opening severity) |
| low | Recovering episode with healthy streak >=3; peak_severity retains prior operational impact; resolved episodes keep severity=low with peak_severity available in their summary |

Store actual input bucket IDs and the rule/values in severity_reason. Impact boundaries are not detector thresholds. Escalation is immediate on evidence; demotion to low only at recovering. For open episodes retain the maximum severity observed within that episode; do not oscillate with one quiet minute. On recovering-to-open, restore at least peak_severity and evaluate new evidence for escalation.

### Baseline, recovery, resolution

Freeze up to the previous 30 complete one-minute buckets before first_affected_at, requiring at least 10. Exclude minutes with positive results from either registered service detector; use only minutes for which both detector results are available and valid. Freeze median minute p95 and median minute error rate. This is a reference median, not the overall request p95. If unavailable, recovery_baseline=null, reason baseline_missing; automatic recovery is disabled. Retry baseline collection as delayed pre-incident evidence arrives, but never substitute post-fault minutes. A frozen baseline is not recomputed to adapt to the fault.

A healthy recovery minute must satisfy all:

- It follows last_affected_at; bucket is finalized, complete, >=20 samples, full sampling, no known late-data issue.
- Both service detectors have a valid non-positive (zero) grade for that source minute, preventing race with delayed results. Missing/error results do not count.
- `latency_p95_ms <= baseline.latency_p95_median_ms * 1.20 + 10ms`.
- `error_rate <= min(1, baseline.error_rate_median + 0.01)`.
- For live transitions, latest considered bucket end is no more than 300s behind wall clock and raw ingestion freshness <=120s. Historical reconciliation may evaluate historical completeness without pretending it is live health.

Three consecutive healthy minute windows transition open → recovering. Five transition recovering → resolved. Count each bucket once with last_recovery_bucket_end. Any unhealthy/anomalous minute resets streak and recovering → open. A missing minute, partial result, or stale telemetry resets the consecutive streak and blocks resolution; existing recovering state may remain displayed with unknown health until fresh evaluation. Record resolved_at as decision time and the recovery evaluation boundary in the worker processing envelope for historical assignment.

RCF grade zero alone is never recovery. A later positive result for a recovery minute triggers chronological reevaluation; the episode can reopen if the resolution was invalid. A genuinely new fault after verified resolution opens a new episode.

ServiceHealth: unknown if raw freshness >120s, latest finalized bucket >300s old, insufficient/unknown input, unready detector, or failed required query. Otherwise unhealthy if any active critical/high episode; degraded if another open/recovering episode exists; healthy only with eligible fresh buckets and both ready detectors and no active episode. An uninstrumented service is unknown, not healthy.

## 5. Evidence selection and storage limits

All values below are maximums, not minimum promises. Select deterministically; never fill shortages with fictional records.

| Evidence type | Per-bundle bound | Selection |
|---|---|---|
| anomaly_result | 10 | Trigger first, then latest results by affected time/ID |
| metric_bucket | 60 | Trigger bucket, baseline summaries' available references, recent affected/recovery minutes |
| log_record | 50 | ERROR/FATAL first, then trace-linked logs; severity descending, time ascending, stable ID |
| trace | 5 | Error traces first, then highest observed server duration, trace ID tie-break |
| span | 30 standalone | Relevant client/server/error spans not already adequately represented |
| error_group | 10 | Count descending, fingerprint ascending |
| dependency_edge | 20 | One-hop neighbors, source/target IDs ascending |
| native_metric | 20 | Allowlisted corroborating metrics; no counter-rate conversion without a later contract |

Maximum 200 spans per TraceSnapshot, 256 KiB per EvidenceItem, 300 items and 2 MiB per bundle. Truncate individual text fields first; if item still oversized, reduce trace span list deterministically and mark partial, or omit item with an explicit bundle limitation. Retain triggering anomaly + metric evidence ahead of optional logs/traces. Stop before byte limit, set truncated; byte limits override item counts.

Redaction happens before persistence or provider use. Allowlist fields; drop bodies/query strings/auth headers/secrets and omit scenario-control labels. Log body scrubber policy is versioned; unknown structured attributes are not copied automatically. Every stored item has redaction_status checked_clear or redacted. Summaries use redacted content only.

Content hashes use RFC 8785 canonical JSON of the typed redacted snapshot. Evidence ID: `H("ev",[evidence_type,canonical source identity string,content_sha256,redaction_version])`. Different source version/content produces a new item; retrieved_at alone does not change identity. Identical item reuse preserves its original provenance; later retrievals are recorded in the tool execution ledger.

Bundle ID: `H("bundle",[incident_id,revision,ordered evidence ID digest])`. Persist items first, then immutable bundle, then CAS incident bundle pointer/version. Orphan items/bundles are safe for later retention cleanup; readers only use committed references. Default max 20 bundles per incident. Preserve first bundle, latest bundle, and all referenced investigation bundles; at cap stop automatic bundle creation and expose truncation, never overwrite referenced snapshots. Cap five automatic and five user-triggered jobs per incident. With bounded bundles/jobs, an indefinitely open episode cannot accumulate unlimited evidence. Raw anomaly records remain governed by retention.

Refresh bundles only when a new anomaly minute materially changes evidence, evidence previously failed becomes available, or recovery changes state; minimum 60s between automatic collections. At cap continue incident state/count updates and show that evidence history is capped.

## 6. Investigation scheduling and recovery

Automatic job key: incident_id + evidence_bundle_id + prompt_version + tool_contract_version + literal `automatic`; ID is H("inv", those parts). First committed bundle queues one job. Later jobs require a newly affected service or severity escalation, a newer bundle, and >=10min since previous automatic job. Maximum five automatic jobs/episode. A periodic reconciliation scan finds committed eligible bundles missing a job, covering crashes between incident and job writes.

User job ID: `H("inv",[principal_id,incident_id,idempotency_key])`. Require Idempotency-Key header. Same key with changed effective body/incident scope ->409; exact retry returns same persisted ID and 202, even if job now terminal. Bind initial evidence_version in stored job. At most one nonterminal job per incident enforced by the singleton scheduling path plus conditional incident scheduling reservation described in storage.md; if another key races, return409 with active job ID, not another provider run. User cap five jobs/episode and 60s minimum interval; retries of same key bypass quota increments.

Job claiming: conditional update of queued due job or expired running lease, using `_seq_no`/`_primary_term`; assign attempt_id/owner, increment attempt_count, set 90s lease. Attempt deadline 60s; heartbeat every 15s extends lease only if attempt still matches. Completion requires same unexpired attempt_id and current CAS token. A timed-out/expired worker cannot publish over a newer attempt. Persist final report and succeeded state in one job document update.

Maximum three attempts. Retry transient provider/rate/storage failures with delays 30s then 120s plus deterministic 0..5s jitter derived from job ID. Schema/citation/forbidden failures are terminal after the one bounded output-repair opportunity described in agent.md. Rescan all due jobs and expired leases; an advisory scan cursor never hides old work. At-least-once execution means a crash after a provider call can incur duplicate provider cost; never advertise exactly-once calls.

Request/context evidence is read-only to the agent. The host runner writes jobs, audit records and validated evidence/results using separately scoped repository capabilities.

## 7. Required later-phase regression cases

Phase 4: same span twice, replay across midnight/rollover, same ID conflicting content, redaction, cross-service trace continuity.

Phase 5: minute boundary, client/server double-count prevention, 4xx vs5xx, ERROR status with/without status code, 0/19/20 requests, units, offset detector windows, missing and late buckets, sampling drift, real cold-start and warmed faults.

Phase 6: crash at each persistence step, overlap pagination ties, old execution-time result outside overlap, repeated positive grade same result, both feature episodes, related-but-not-causal dependencies, persistent fault after RCF adapts, late contradiction to recovery, stale telemetry, missing baseline, bounded evidence over a long incident.

Phase 7: expired lease/stale completion, duplicate POST, provider timeout/cost duplication, invalid citations, telemetry prompt injection, unavailable tools, budget exhaustion, evidence expiry and truncation.
