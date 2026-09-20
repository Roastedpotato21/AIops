# Phase 6 Completion

## Outcome

**PASS.** The deterministic incident engine, bounded evidence collection, recovery policy, persistent worker, strict storage mappings, and incident read APIs pass focused tests and a live container path using an explicitly labeled development fixture. No fixture is represented as a genuine RCF result.

## Scope implemented

- `backend/app/incidents`: deterministic anomaly assignment, one active episode per service/feature/policy, frozen baseline, impact severity, recovery, evidence selection, redaction, byte/item bounds, and evidence-backed related-incident links.
- `backend/app/models/incidents.py`: strict incident, evidence, timeline, API envelope, pagination, and worker progress models.
- `backend/app/repositories/incidents.py`: bounded OpenSearch reads/writes for anomalies, buckets, incidents, evidence, APIs, and worker progress.
- `backend/app/workers/incidents.py`: persistent singleton-style polling of pending/assigned normalized anomalies with idempotent replay and durable progress.
- `backend/app/api/incidents.py`: `GET /api/v1/incidents`, `GET /api/v1/incidents/{id}`, and `GET /api/v1/incidents/{id}/evidence` only.
- `scripts/bootstrap.py`: additive strict mappings for `aiops-incidents-v1` and `aiops-evidence-v1`, incident cursor fields, API read access, and worker access.
- `docker-compose.yml`: private incident worker with no published port.
- `backend/tests/test_incidents.py`: focused Phase 6 contract tests.

No reasoning agent, LLM/provider, investigation jobs, remediation, runbook search, frontend incident pages, or other Phase 7+ behavior was added. Phase 5 aggregation and RCF semantics were not changed.

## Focused tests and checks

- `uv run --project backend pytest backend/tests/test_incidents.py backend/tests/test_config.py backend/tests/test_health.py -q`: **15 passed**, with two upstream Starlette/httpx deprecation warnings.
- Focused Ruff check over Phase 6 and directly changed files: **passed** after import/line formatting corrections.
- `python -m py_compile scripts/bootstrap.py backend/app/workers/incidents.py`: **passed**.
- `docker compose -f docker-compose.yml -f docker-compose.dev.yml config --quiet`: **passed**.
- Full Phase 1–5 regression: **not run**, per deadline authorization.
- Phase 9 live closure: bootstrap completed idempotently; the incident worker became healthy; incident detail and evidence APIs returned 200.
- Phase 9 final targeted boundary: **34 passed** across incident, investigation, worker-role, config, and health tests; focused Ruff and Compose render passed.

## Incident creation and deduplication

Focused tests prove an eligible normalized anomaly and detector-ready finalized bucket create `H("incident", [service_id, feature, opening_anomaly_id, policy_version])`. A second distinct positive anomaly attaches to the same active episode and increments the distinct anomaly count. Replaying the same normalized anomaly returns the same incident without creating a bundle or incident duplicate. Independent features create separate incidents.

## Evidence bundle

The first bundle prioritizes the normalized anomaly and triggering metric bucket, then frozen baseline buckets, followed by bounded ERROR logs, error spans, up to five reconstructed traces, and up to twenty observed dependency edges when available. Evidence IDs and bundle IDs are content-derived. Items are limited to 256 KiB; bundles to 300 items and 2 MiB. Redaction precedes persistence. Focused tests prove stable IDs, committed bundle references, and explicit truncation.

## Severity and baseline

The frozen baseline uses 10–30 eligible finalized pre-incident buckets and median minute p95/error rate. Policy `1.0.0` assigns critical for error rate at least 0.20, high for error rate at least 0.05 or latency at least three times baseline, and medium for other eligible positives. Grade/confidence is not used as operational severity. Open episodes retain peak severity.

## Recovery lifecycle

Fresh finalized full-sampling buckets, both detector grades at zero, baseline thresholds, raw freshness at most 120 seconds, and bucket freshness at most 300 seconds are all required. Three consecutive healthy minutes transition to recovering; five resolve; duplicate buckets do not increment; stale/missing input blocks recovery; recurrence resets the streak and reopens a recovering episode. Focused recovery tests passed.

## Correlation

Same-service different-feature episodes link as `same_service_overlap`. Cross-service episodes link only within five minutes and only when a stored trace includes both services or an observed dependency edge connects them. Links are symmetric and non-causal; incidents are never merged and suspected root service remains null. Focused dependency-backed cross-service correlation passed.

## API

All three Phase 0 incident GET endpoints return typed envelopes, bounded pages, normalized models, evidence in stored bundle order, and an explicit `fixture_source` label. Focused API tests retrieved list, detail, and evidence successfully and exposed no storage endpoint details. Pagination cursors are rejected until a valid signed cursor exists rather than accepting an unsafe token.

## Real RCF or fixture source status

No genuine post-warm-up positive RCF result was available. The guarded live fixture used the exact `NormalizedAnomaly` contract and source index `phase6-development-fixture`; the resulting projection retained `fixture_source=true` throughout storage, API, and UI.

- Normalized anomaly: `anomaly_ed14b35d674c046f0754c976fb24a3fb8be315983640ef5249dee861a526c59c`.
- Incident: `incident_5d66753c8b4fdb7a84cdd3d745be6e094ad09748acc18eca05b68e6740ee9b59`, state `open`, severity `medium`.
- Evidence bundle: `bundle_14d48c515c1d86170da89ef52d968fa6b2c9bc58339affa77eb946b56c4f67ea`, revision 1, 33 items, 94,720 bytes, quality `complete`.
- Incident detail and evidence retrieval both returned HTTP 200.

## Contract clarifications

The Phase 6 handoff requires fixture incidents to remain visibly distinct from genuine detector incidents. The stored incident and API summary therefore add `fixture_source:boolean`, default false, as a narrow additive clarification. It does not alter episode identity, severity, recovery, or native anomaly contracts.

## Remaining blocker

The Phase 6 live-container blocker is closed. Signed continuation cursors remain a scale-hardening item; current requests with a cursor fail closed. Genuine native RCF positive evidence remains a separate Phase 5/9 live-validation item and was not fabricated.

## Phase boundary

STOP. Await a separate Phase 7 handoff; do not begin Phase 7 automatically.
