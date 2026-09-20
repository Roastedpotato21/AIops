# Phase 9 Completion

## Outcome

**PASS — LIVE LOCAL-BETA ACCEPTANCE COMPLETE; PHASE 10 READY.** Current targeted images build and run, least-privilege identities are proven live, Phase 6 and Phase 7 container blockers are closed, the persisted React/API flow is browser-verified, and one controlled restart plus one OpenSearch outage preserve logical state. Native RCF positive evidence remains pending solely because all six detectors are still in genuine INIT; no anomaly was fabricated.

## Scope and corrections

- Recovered from the prior Docker data-VHD failure without prune, reset, volume deletion, or project rebuild. A recurrence during automatic container restore was captured in `docker-desktop-diagnostics-post-repair-recurrence-20260920.zip`; stopping the project before a restart surge stabilized the engine.
- Corrected one-shot Python entrypoints to module execution so `app` imports resolve in containers.
- Added the exact OpenSearch 3.8 bulk transport permission `indices:data/write/bulk` to API and split worker identities while preserving index-level ownership. The broader `cluster_composite_ops` group was explicitly rejected because it also grants alias/reindex actions.
- Strengthened the live permission checker to create and immediately remove a valid probe in each worker's owned index, then require a representative forbidden write to return 403.
- Corrected investigation claim searches to request `_seq_no`/`_primary_term` for CAS and hydrated persisted UUID-bearing jobs through strict JSON validation.
- Corrected two long-running-session tests to use deterministic offsets from a current UTC anchor instead of an expired absolute deadline.
- Built the current frontend in the authoritative digest-pinned Node 24.21.0 Alpine image using locked optional dependencies.

No Phase 10 deployment, public edge, authentication, cloud provisioning, remediation, or new product architecture was implemented.

## Docker stability and targeted images

After recovery, Docker Engine 29.6.1 and BuildKit were responsive. Targeted serial builds passed for API, incident worker, investigation worker, bootstrap, Phase 9 fixture, permission checker, and frontend. The frontend build installed 273 locked packages with zero reported vulnerabilities and transformed 601 modules. The final stack remained stable through targeted builds, one full project stop/start, one OpenSearch stop/start, and final live checks.

The final running health-checked services were healthy: OpenSearch, Data Prepper, Collector, API, frontend, aggregation worker, incident worker, investigation worker, and all three demo services. Dashboards was running privately. Published ports remained loopback-only at API 8000 and frontend 4173; storage, ingestion, workers, demo services, and Dashboards had no host publication in the active development configuration.

## Least-privilege authorization

Bootstrap completed idempotently after applying current roles. Final live results for aggregation, incident, and investigation identities were identical:

- intended read: HTTP 200;
- intended document write: HTTP 201;
- probe cleanup: HTTP 200;
- representative forbidden write: HTTP 403.

Normal worker operation also persisted buckets, incident/evidence records, worker state, and the investigation report. The legacy broad worker role remains emptied and unmapped.

## Phase 6 live result

The guarded exact-contract fixture path completed:

- normalized anomaly `anomaly_ed14b35d674c046f0754c976fb24a3fb8be315983640ef5249dee861a526c59c`;
- incident `incident_5d66753c8b4fdb7a84cdd3d745be6e094ad09748acc18eca05b68e6740ee9b59`;
- evidence bundle `bundle_14d48c515c1d86170da89ef52d968fa6b2c9bc58339affa77eb946b56c4f67ea`;
- state `open`, severity `medium`, `fixture_source=true`;
- evidence revision 1, 33 items, 94,720 bytes, quality `complete`;
- incident detail and evidence APIs: HTTP 200.

The UI and stored evidence label the source as a development fixture not produced by live RCF.

## Phase 7 live result

FastAPI returned 202 and queued investigation `inv_2ab43c9632d668dd0b755814e7fe842a7a59158b22dea9bd9eca20547c52ebaf`. The first live claim exposed the CAS/UUID storage defects described above; after the targeted fixes, the expired lease was reclaimed and the job completed on attempt 2.

Final result:

- state `succeeded`, `fixture_source=true`;
- one allowlisted read-only incident tool path;
- supporting evidence `ev_55c39adfeb6866e718e160a720d5011ebcc9b63d91ebb5e5827a150a7554118c`;
- low qualitative confidence and `completion_status=insufficient_evidence`;
- no suspected root service, no causal claim, and no executed remediation;
- explicit limitations that the provider is deterministic/non-external and the incident is not genuine RCF evidence;
- persisted investigation GET: HTTP 200.

No external LLM credential was requested, discovered, printed, or used.

## Persisted UI result

Browser automation verified the current React operations UI against the live API and persisted OpenSearch records:

- overview showed one medium open payment incident, visibly marked `FIXTURE`, with investigation available;
- incident detail showed fixture provenance, chronology, 33 evidence items, and the dependency edge;
- investigation report showed `SUCCEEDED`, low confidence, insufficient evidence, no established root, and both required limitations;
- incident, evidence, investigation, overview, and service API requests returned HTTP 200;
- browser console and page-error collections were empty;
- screenshot: `docs/assets/screenshots/phase9-persisted-incident.png`.

During the controlled OpenSearch outage, the frontend showed `Not ready` with OpenSearch and bootstrap unreachable. The restarted Compose frontend initially exposed a stale Phase 1 image; a targeted current-image rebuild/recreate corrected it, and the containerized page then passed the same persisted markers with no console/page errors.

## RCF result

One direct bounded profile inspection succeeded after the broader Phase 5 inspector helper hung and was stopped. All six real detectors returned HTTP 200 with native state `INIT`, initialization `0%`, estimated 32 minutes, 32 needed shingles, and no data in the current window. Detector semantics were not changed and no latency/error anomaly was fabricated. This is the sole reason genuine positive native/normalized IDs remain unavailable.

## Restart and persistence

One controlled Compose project stop/start completed without deleting volumes. Before restart:

- service metrics 1,693; anomalies 201; incidents 1; evidence documents 34; investigations 1; worker-state records 11.

After restart:

- anomalies 201; incidents 1; evidence documents 34; investigations 1; worker-state records 11;
- exact incident, bundle, and investigation IDs remained readable;
- service metrics advanced to 1,748 as the aggregation worker resumed catch-up, then continued progressing;
- no duplicate logical incident, evidence bundle, or investigation appeared.

## OpenSearch outage and recovery

Exactly one OpenSearch-only outage was run:

- `/health` remained 200;
- `/ready` returned 503 with OpenSearch/bootstrap `unreachable`;
- `/api/v1/overview` returned 503 `dependency_unavailable`;
- frontend rendered the unavailable state rather than false health;
- aggregation stayed alive; incident and investigation workers failed closed and restarted under Compose;
- after restore, `/ready` and overview returned 200, all workers returned healthy, exact IDs remained readable, and logical counts remained 201 anomalies / 1 incident / 34 evidence / 1 investigation.

The restart-loop behavior of incident/investigation polling during dependency loss is safe but noisy and remains a resilience improvement. Separate Collector/Data Prepper interruption matrices were not repeated under the deadline verification schedule.

## Retention, rollover, mapping, and runtime

- Selected beta retention remains 7 days raw telemetry/service map, 30 days buckets/native/normalized anomalies, and 90 days resolved incidents/evidence/terminal investigations with reference-aware deletion.
- The installed `raw-span-policy` rolls over at 24 hours / 50 GiB but contains no delete transition. Full 7/30/90 enforcement, disk alerts, and snapshots remain Phase 10 deployment blockers; no risky deletion policy was attached to useful evidence in this pass.
- Span alias inspection showed four backing indexes and exactly one write index (`otel-v1-apm-span-000004`). Physical cross-rollover duplicate/conflict staging was not forced.
- Point-in-time sizing: 58,829 spans / 18.5 MiB; 47,957 raw metrics / approximately 21.3 MiB across two daily indexes; 10,445 logs / approximately 2.6 MiB across two daily indexes. This is not a capacity claim.
- The preserved local `aiops-worker-state-v1.last_error` mapping is still non-indexed keyword. Healthy operation is unblocked, so no destructive migration was performed. Clean bootstrap and the documented versioned reindex/alias migration remain authoritative.
- Digest-pinned Node 24.21.0 Alpine is the validated release runtime. Local Node 22 is not release evidence, and engine requirements were not weakened.

## Final targeted verification

- Focused backend regression over worker roles, investigations, incidents, config, and health: **34 passed**, two upstream Starlette/httpx/AnyIO deprecation warnings.
- Focused Ruff over every changed Python file: **passed**.
- Compose render with both files: **passed**.
- Current frontend container production build: **passed**.
- Final live worker permission check: **passed for all three identities**.
- Final full stack health: **passed**.
- Final persisted incident API, investigation API, and frontend HTTP checks: **200/200/200**.
- `git diff --check`: **passed** before report updates and will be repeated before commit.

Previously passed broad Phase 1–8 suites were not rerun because current changes did not invalidate their accepted evidence.

## Remaining production blockers

- Genuine positive native RCF latency/error evidence remains pending while detectors are INIT; allowed not to block Phase 10 start by the resume handoff.
- Implement and test 7/30/90 retention enforcement, disk alerts, and snapshots before public deployment.
- Run isolated physical cross-rollover replay/conflict validation before production aggregation claims.
- Migrate the preserved legacy worker-state mapping before reusing this volume in production.
- Implement the Phase 10 TLS/auth/rate-limit/public exposure boundary before public deployment.
- Add signed pagination cursors before beta data exceeds bounded first pages.
- Run bounded performance/capacity measurement on the intended deployment shape.
- Improve incident/investigation polling backoff so an OpenSearch outage logs bounded warnings instead of container restart loops.
- Live external-provider validation remains an explicit credential checkpoint and is not required for the deterministic beta.

## Phase 10 readiness

**READY.** Docker is stable, current targeted images build/start, least privilege is proven live, Phase 6 and 7 live paths pass, persisted UI/API passes, restart preserves state, and the OpenSearch outage recovers without duplication. Genuine RCF remains pending only because native initialization has not completed. TLS/auth, retention enforcement, and deployment infrastructure are Phase 10 completion work and must not be omitted before public exposure.

## Phase boundary

STOP. Do not begin Phase 10 automatically.
