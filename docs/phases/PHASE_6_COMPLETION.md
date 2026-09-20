# Phase 6 Completion

## Outcome

**PARTIAL — IMPLEMENTATION COMPLETE / LIVE CONTAINER VALIDATION BLOCKED.** The deterministic incident engine, bounded evidence collection, recovery policy, persistent worker, strict storage mappings, and incident read APIs are implemented and pass focused tests. The required live OpenSearch fixture path was not run because Docker Desktop did not return service state and the execution safety gate rejected creation of the persistent fixture helper; no fixture or RCF result was fabricated.

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
- Incident worker container startup, live bootstrap, live evidence/API retrieval: **not run**. Docker Desktop service-state calls returned no result within repeated 30-second checks.

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

No genuine post-warm-up positive RCF result was available from Phase 5. Unit/integration fixtures use the exact `NormalizedAnomaly` contract and the source index literal `phase6-development-fixture`; resulting incident projections set `fixture_source=true`. A live persistent fixture was not inserted, and no test fixture is claimed as a real detector result.

## Contract clarifications

The Phase 6 handoff requires fixture incidents to remain visibly distinct from genuine detector incidents. The stored incident and API summary therefore add `fixture_source:boolean`, default false, as a narrow additive clarification. It does not alter episode identity, severity, recovery, or native anomaly contracts.

## Remaining blocker

Before marking Phase 6 fully PASS, run bootstrap against the live volume, start `incident-worker`, and complete one explicitly labeled normalized-anomaly fixture or genuine RCF-positive path through incident, evidence, and API retrieval. Docker availability and the rejected persistent-helper write prevented that check in this pass. Signed continuation cursors remain a later API-hardening item; current requests with a cursor fail closed.

## Phase boundary

STOP. Await a separate Phase 7 handoff; do not begin Phase 7 automatically.
