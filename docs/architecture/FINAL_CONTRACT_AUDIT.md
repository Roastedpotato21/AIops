# Final Contract Audit

Audit date: 2026-09-20
Accepted starting boundary: `0a2df4994fa11f74f5d11534e6ebf60e8d278c77`

## Result

**PASS — no locked Phase 0 beta product requirement remains unimplemented.**

The complete architecture exists from instrumented applications through persisted dashboard views. This audit found and closed four narrow contract gaps: the bounded direct-trace API, native-metric evidence in the metrics tool, normalized related-error groups, and strict contract-shaped API validation/error handling. No architecture, detector semantics, incident policy, or security boundary was weakened.

`COMPLETE` means implemented with focused tests or accepted live evidence. `DEPLOYMENT-PHASE` means intentionally owned by the secure AWS deployment. `VALIDATION-PENDING` means the production-oriented implementation exists but the named real-world check is still outstanding. `GENUINE GAP` would mean required beta source behavior is absent.

## Compliance matrix

| Contract requirement | Implementation location | Test or live evidence | Status |
|---|---|---|---|
| Order, Payment, and Inventory application flow | `apps/order-service`, `apps/payment-service`, `apps/inventory-service` | Phase 2/3 service tests and connected trace | COMPLETE |
| OTel traces, correlated logs, and native metrics | `apps/telemetry/aiops_telemetry` | Phase 3 live trace/log/metric evidence; 17 focused app tests | COMPLETE |
| Collector → Data Prepper → OpenSearch three-signal path | `infra/otel`, `infra/data-prepper`, Compose | Phase 1 compatibility probe; Phase 3/5 persisted application evidence | COMPLETE |
| Native trace/service-map mapping ownership | Data Prepper configs and `telemetry-field-map.md` | Synthetic service-map probe plus real application trace | COMPLETE |
| Explicit service identity and deterministic full-length IDs | `backend/app/models`, telemetry adapters | Adapter, aggregation, incident, and fixture tests | COMPLETE |
| One-minute completed-SERVER-span aggregation | `telemetry/aggregation/service.py`, aggregation worker/repository | Boundary, exclusion, error, replay, late-data, and outage tests | COMPLETE |
| Deterministic current-beta nearest-rank p95 | Aggregation service and Phase 5 contract resolution | p95 edge/minimum/skew tests | COMPLETE |
| Six native single-feature RCF detectors | `detection/registry.py`, `provision_detectors.py` | Six stable native detector IDs; OpenSearch profile returned HTTP 200 | COMPLETE |
| Genuine post-warm-up positive RCF results | Existing native detectors and inspector | All six remained native `INIT`, 0%, 32 shingles required | VALIDATION-PENDING |
| Native-result normalization with exact bucket association | `detection/adapters.py`, Phase 5 inspector | Adapter tests and 136 genuine non-positive operational results | COMPLETE |
| One active incident per service/feature/policy | `incidents/engine.py`, incident repository | Deduplication, replay, distinct-feature, and live fixture incident | COMPLETE |
| Deterministic anomaly, incident, evidence, bundle, and job IDs | Models, engine, evidence, scheduling | Replay/idempotency tests and stable live IDs | COMPLETE |
| Frozen 10–30 minute pre-incident baseline | `incidents/policy.py` | Focused baseline and incident creation tests | COMPLETE |
| Three healthy minutes to recovering; five to resolved | `incidents/policy.py`, engine | Recovery, stale-input, replay, and recurrence tests | COMPLETE |
| Impact-based severity independent of anomaly grade | Incident policy | Deterministic severity tests | COMPLETE |
| Bounded, typed, redacted evidence with provenance | `incidents/evidence.py`, evidence models | Stable-ID/truncation tests; live 33-item, 94,720-byte bundle | COMPLETE |
| Separate persistent incident and investigation workers | `workers/incidents.py`, `workers/investigations.py`, Compose | Live worker startup, writes, restart, and outage recovery | COMPLETE |
| Exactly seven allowlisted read-only agent tools | `agent/tools.py`, `agent/backend.py` | Scope/budget tests plus focused native-metric/error-group tests | COMPLETE |
| Agent deadlines, token/cost/evidence bounds and citation validation | Investigator, provider boundary, strict models | Provider failure, invalid citation, budget, and prompt-injection tests | COMPLETE |
| No autonomous remediation | Tool registry and report validators | Unknown shell/write tool rejection; `executed=false` enforcement | COMPLETE |
| Fixture provenance never masquerades as native RCF | Development fixture, incident/investigation models, UI | Live fixture incident/report and browser screenshot | COMPLETE |
| FastAPI health, dashboard, incident, evidence, trace, and investigation boundaries | `backend/app/api` | Focused API tests; live incident/evidence/investigation HTTP 200 | COMPLETE |
| Contract-shaped safe HTTP errors | `api/errors.py` | Focused dependency and validation envelope tests | COMPLETE |
| React/TypeScript/Vite operations dashboard | `frontend/src` | Build, component tests, and containerized browser verification | COMPLETE |
| OpenSearch as the only application datastore | Repositories, Compose, storage contract | Live persistence and restart count/ID checks | COMPLETE |
| Least-privilege component identities | `opensearch/roles.py`, bootstrap | Intended reads/writes 200/201; forbidden writes 403 | COMPLETE |
| Replay and crash-safe persistence boundaries | Repositories and all three workers | CAS, replay, late-data, idempotency, restart tests | COMPLETE |
| Public TLS, authentication, rate limiting, and network edge | Phase 10 deployment scope | Not present locally; current publications are loopback-only | DEPLOYMENT-PHASE |
| 7/30/90 retention, snapshots, and disk alarms | Selected policy in blocker register | Policy chosen; enforcement deliberately not attached locally | DEPLOYMENT-PHASE |
| Legacy worker-state mapping on the preserved local volume | Clean bootstrap plus migration plan | Healthy local operation; no destructive migration performed | DEPLOYMENT-PHASE |
| Physical cross-rollover replay/conflict behavior | Alias-wide deduplication code and native rollover | Unit behavior passed; forced two-backing-index stress not run | VALIDATION-PENDING |
| External provider network/usage behavior | OpenAI provider adapter | Credential-free provider boundary passes; no credential authorized | VALIDATION-PENDING |
| Bounded deployment-shape performance | Phase 10 target infrastructure | Development counts exist but are not a capacity claim | DEPLOYMENT-PHASE |

## Architecture confirmation

```text
Applications → OTel → Collector → Data Prepper → OpenSearch
→ one-minute aggregation → native RCF → normalized anomalies
→ deterministic Incident Engine → evidence bundles
→ separate Investigation Worker → bounded read-only agent
→ FastAPI → React/TypeScript/Vite
```

Every arrow above has source code and either focused test evidence, live local evidence, or both. The absence of a post-warm-up positive RCF result is an explicit validation gap, not an implementation substitute: detectors remain native and no positive result was inserted.

## Reconciled pending work

- **Validation pending:** genuine positive native RCF latency/error results; physical cross-rollover stress; one explicitly authorized external-provider request.
- **Phase 10 deployment work:** TLS/auth/rate limiting, public network boundary, 7/30/90 retention enforcement, snapshots, disk alarms, legacy-volume migration if reused, and bounded target-shape performance measurement.
- **Post-beta scale hardening:** signed continuation cursors before datasets exceed the current bounded first-page UI, multi-node availability, and larger-scale capacity/SLO claims.

The current fail-closed cursor behavior does not expose unsafe native tokens and does not block the bounded beta UI. It must be replaced by the specified signed continuation design before scaled pagination is advertised.

## Contract resolutions retained

- The approved Phase 3 trace clarification remains Order → Payment and Order → Inventory in one trace; no Payment → Inventory dependency was introduced.
- The approved Phase 5 beta uses deterministic nearest-rank p95; older TDigest wording is superseded for this release.
- Detector display names remain shortened for OpenSearch's enforced 64-character limit while deterministic service identity remains unchanged.
- Phase 0 canonical stored field names remain authoritative.

## Phase 10 gate

The repository is **ready to begin Phase 10**, not ready for anonymous public exposure. Phase 10 must close its deployment-owned security, durability, retention, and measurement items before publishing the final URL.
