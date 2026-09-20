# Phase 7 Completion

## Outcome

**PASS — IMPLEMENTATION AND LIVE CREDENTIAL-FREE CRITICAL PATH COMPLETE.** Persisted asynchronous investigation jobs, bounded read-only tools, an interchangeable provider boundary, evidence-linked structured reports, and the investigation APIs pass focused tests and live container validation. The deterministic provider is visibly non-external and does not represent fixture output as genuine RCF evidence.

## Scope implemented

- `backend/app/agent`: investigator orchestration, exactly seven allowlisted read-only tools, repository-backed tool implementations, host-side scope/deadline/result guards, scheduling, evidence validation, prompt-injection isolation, provider abstraction, OpenAI Responses API adapter, and deterministic test provider.
- `backend/app/models/investigation.py`: strict job, tool, provider, budget, report, and API contracts.
- `backend/app/repositories/investigations.py`: create-only idempotent jobs, CAS lease claims, delayed bounded retries, persisted outcomes, errors, executions, usage, and evidence references.
- `backend/app/workers/investigations.py`: private polling worker that claims one job, pins the incident evidence version, executes the investigator, and persists success or failure.
- `backend/app/api/investigations.py`: asynchronous `POST /api/v1/incidents/{id}/investigate` and persisted `GET /api/v1/investigations/{id}`.
- `scripts/bootstrap.py` and `docker-compose.yml`: strict investigation index mapping, additive incident scheduling fields, scoped API persistence permission, and a private investigation worker with no host port.

No anomaly, incident-creation, remediation, shell, filesystem, arbitrary URL/DSL, Docker, GitHub, AWS, runbook RAG, historical RAG, frontend investigation page, or Phase 8+ behavior was added.

## Focused tests and checks

- `uv run --project backend pytest backend/tests/test_investigation.py -q`: **15 passed**, with two upstream Starlette/httpx deprecation warnings.
- Directly affected shared boundary: `uv run --project backend pytest backend/tests/test_incidents.py backend/tests/test_config.py backend/tests/test_health.py -q`: **15 passed**, with the same two upstream warnings.
- Focused/full backend Ruff boundary over `backend/app`, the Phase 7 test, and bootstrap: **passed**.
- Python compilation for the worker and bootstrap: **passed**.
- `docker compose -f docker-compose.yml -f docker-compose.dev.yml config --quiet`: **passed**.
- Live API scheduling returned 202; the private worker claimed the persisted job, performed the allowlisted deterministic read, persisted a validated report, and the GET API returned 200.
- Full Phase 1–6 regression: **not run**, per deadline verification policy.

## Investigation job result

The live HTTP path returned 202 and queued `inv_2ab43c9632d668dd0b755814e7fe842a7a59158b22dea9bd9eca20547c52ebaf`. A live-only defect was fixed: claim searches now request OpenSearch sequence/primary-term metadata for CAS, and persisted JSON UUIDs are hydrated through strict JSON validation. The worker reclaimed the expired first lease and completed on attempt 2. The final state is `succeeded`, with pinned evidence `ev_55c39adfeb6866e718e160a720d5011ebcc9b63d91ebb5e5827a150a7554118c`, low confidence, no root-cause claim, no executed remediation, and `completion_status=insufficient_evidence`.

## Tool and evidence safety

The registry exposes only `get_incident`, `search_logs`, `search_traces`, `get_trace`, `get_metrics`, `get_service_dependencies`, and `find_related_errors`. Strict models reject unknown DSL/write/shell fields. Host validation enforces incident ID, service IDs, the pinned incident window, a 30-minute per-call range, allowed metric names, cursor policy, result limits, an eight-call cap, a 60-second wall-clock deadline, token/cost bounds, and additional-evidence item/byte limits. Tool records are redacted before persistence and log text is explicitly untrusted evidence.

Every report citation is checked against the pinned bundle plus evidence actually returned by tools. Unknown evidence IDs, out-of-scope services, and executed actions fail the job. Insufficient evidence remains a valid explicit report state. Fixture-backed reports retain a limitation stating that they are not evidence of a genuine RCF anomaly.

## Provider boundary and credential checkpoint

`ReasoningProvider.generate(...)` is interchangeable. Tests use only the deterministic provider. The real adapter follows the official OpenAI Responses API function-calling pattern with host-executed strict tools, structured JSON-schema output, and `store: false`: <https://developers.openai.com/api/docs/guides/function-calling>.

No LLM credential was created, discovered, printed, committed, reused, or required. No live-provider request was attempted. Before the first live-provider validation, explicit user authorization and a user-supplied credential are required.

## Contract deviations

None. The API uses an `Idempotency-Key` header to supply the principal-scoped idempotency value required by the contract. Suggested remediation remains non-executing text (`executed=false`).

## Remaining blockers and deferred checks

- The OpenAI adapter has not been live-validated because no credential was authorized; this is an explicit credential checkpoint, not an implementation shortcut.
- Genuine native RCF positive input remains pending; the accepted live report retains fixture provenance and explicit non-external/non-RCF limitations.

## Phase boundary

STOP. Await a separate Phase 8 handoff; do not begin Phase 8 automatically.
