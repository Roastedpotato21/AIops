# Phase 9 Completion

## Outcome

**BLOCKED — REGRESSION PASSED, LIVE FULL-STACK ACCEPTANCE INCOMPLETE.** Source hardening and the complete host regression checkpoint pass, but recurring Docker Desktop/BuildKit control-plane stalls prevented rebuilding the affected images and therefore blocked genuine RCF, live Phase 6/7, restart/outage, full end-to-end, performance, and browser acceptance. No live result was fabricated.

## Scope completed

- Added an idempotent exact-contract Phase 9 normalized-anomaly fixture builder and guarded CLI seeder. It refuses to run unless development fixtures are explicitly enabled and retains `phase6-development-fixture` provenance.
- Added a credential-free deterministic provider inside the existing Phase 7 provider boundary. It is available only when environment is development, fixtures are enabled, and provider is exactly `deterministic`. It performs one allowlisted `get_incident` read, cites pinned evidence, makes no causal/root claim, executes no action, and labels itself as non-external output.
- Added focused fixture/provider tests and Compose wiring; no Phase 10 deployment or unrelated product capability was implemented.
- Corrected frontend container installation to include locked optional native packages required by Rolldown on Alpine. The authoritative release runtime remains digest-pinned Node 24.21.0.
- Created the production-blocker register, selected the contract-aligned beta retention policy, and specified rollover, migration, authentication, and public exposure gates.

## Baseline and environment

- Started from clean Phase 8 commit `c34b4d2b3b71b7a677e781660bad7abd94dfda7c`; the only pre-existing Phase 9 worktree change was the in-progress frontend Dockerfile correction.
- Docker Desktop was initially stopped. One clean hidden start recovered Docker Desktop 4.81.0 / Engine 29.6.1. No prune, volume deletion, or `down -v` occurred.
- Host had approximately 291 GiB free. Docker reported 8 CPUs and 3.99 GiB memory; that memory allocation is adequate for local validation only and is not a production sizing claim.
- Required local OpenSearch/API/Data Prepper/worker secret variable names were present. Values were never printed. `.env` is ignored and untracked.
- Compose rendered successfully. Expected published development ports are API `127.0.0.1:8000`, frontend `127.0.0.1:4173`, and optional Dashboards `127.0.0.1:5601`; storage, ingestion, workers, fault controls, and demo services remain private. The running older Dashboards container had no host binding.

## Failure protocol results

1. A parallel multi-image build stalled during export. Classification: Docker/runtime. Diagnosis: Docker Desktop BuildKit/control-plane instability. One targeted Docker Desktop restart recovered the engine; no repeated restarts were performed.
2. The serial frontend container build failed because Rolldown's Alpine optional binding was absent. Classification: dependency/version portability. Targeted fix: `npm ci --include=optional`. The affected rebuild then stalled inside Docker and was interrupted; source/host build passes, container result remains open.
3. Phase 9 fixture test collection failed because backend pytest restricts `pythonpath` to `backend/`. Classification: test/environment and module ownership. A root `scripts` package marker did not resolve it. The builder was moved to the correct typed `app.incidents` module and the CLI retained transport only; the affected suite then passed.
4. The final incident-worker build progressed only through BuildKit definition/metadata loading and then stopped returning output. Classification: Docker/runtime. It was interrupted after bounded polling and not retried.
5. Headless Edge returned no result within the bounded browser window. Classification: test/environment. The exact helper process was stopped; browser acceptance is not claimed.

## Regression checkpoint

- `uv run --project backend pytest backend/tests -q`: **66 passed**, two upstream Starlette/httpx/AnyIO deprecation warnings.
- `uv run --project apps pytest -c apps/pyproject.toml apps/tests -q`: **17 passed**, five upstream OpenTelemetry logging-handler deprecation warnings (run earlier in this Phase 9 checkpoint; apps were not changed afterward).
- `uv run --project backend ruff check backend/app backend/tests scripts apps`: **passed**.
- Focused Phase 9 provider/fixture suite: **15 passed**, same two upstream backend warnings.
- `npm run test -- --run`: **7 passed**.
- `npm run lint`: **passed**.
- `npm run typecheck`: **passed**.
- `npm run build`: **passed**, 601 modules transformed.
- `docker compose -f docker-compose.yml -f docker-compose.dev.yml config --quiet`: **passed**.
- `git diff --check`: **passed**.

## Live stack health

Before the final build stall, bootstrap completed idempotently and `docker compose up -d` created the incident and investigation workers. The live API returned 200 for `/health` and `/ready`; the frontend returned 200 with title `AIOps Operations`. Overview reported OpenSearch healthy but overall state unknown because detector/worker visibility and telemetry freshness were incomplete. Services returned three registered services, with detector-unready or pipeline-stale reasons. Incident count was zero.

These observations prove the previously built local API/frontend remained reachable, not that the new Phase 9 worker images ran. A complete current-image container health result is therefore **not passed**.

## RCF live anomaly result

**NOT RUN / BLOCKED.** Both Compose-run and direct container inspection attempts stopped returning output during Docker control-plane instability. The last accepted Phase 5 evidence had the six real detectors in native initialization and no positive anomaly. Phase 9 captured no READY transition and no positive grade/confidence/native/normalized ID.

## Phase 6 live path

**IMPLEMENTED AND UNIT-VALIDATED; LIVE BLOCKED.** The new seeder selects a real finalized, complete, zero-late-span, detector-eligible payment latency bucket and writes one deterministic exact `NormalizedAnomaly`. It requires at least 11 eligible buckets, is disabled by default, and has stable source/anomaly identity. The current image could not be built/run, so no incident or bundle ID is claimed.

## Phase 7 live path

**IMPLEMENTED AND FOCUSED-VALIDATED; LIVE BLOCKED.** Tests prove all three runtime guards, one allowlisted read-only tool call, pinned evidence citations, fixture limitation, deterministic report timestamp, no root claim, no remediation, and honest `insufficient_evidence`. The current investigation-worker image could not be built/run, so no persisted job/report ID is claimed.

## End-to-end, persistence, outage, and performance

- Full real request → RCF → incident → investigation → dashboard: **blocked** by missing RCF and current-image worker validation.
- Controlled project restart/persistence: **not run**. The one Docker Desktop recovery incidentally preserved volume-backed telemetry, but exact IDs/cursors/dedup were not compared.
- Collector/Data Prepper/OpenSearch interruption checks: **not run** after control-plane instability; no additional Docker cycling was attempted.
- Bounded performance sanity check: **not run** because the current stack could not be controlled reliably. No capacity claim is made.

## Browser result

**BLOCKED.** Live HTTP checks confirmed frontend, Overview API, Services API, and empty Incidents API availability. Frontend component tests cover Overview, Services, service detail, incident detail/evidence/investigation states, and unavailable-state rendering. The bounded headless Edge run hung before producing route evidence; incident detail and investigation could not exist without the blocked live fixture path. No screenshot or console/network pass is claimed.

## Security and exposure

- Rendered host mappings are loopback-only and contain no OpenSearch, Data Prepper, OTLP, worker, demo-service, or fault-control publication.
- OpenSearch security/TLS remains enabled; runtime users are separate from admin. Secret scanning found only `.env.example` placeholders and the local secret generator template. `.env` is ignored and untracked.
- The browser talks only to FastAPI. No frontend credential or OpenSearch endpoint is embedded.
- Agent/provider contracts expose seven typed tools and no arbitrary DSL, URL, shell, Docker, GitHub, cloud, remediation, or infrastructure capability. Report citations and action flags remain host-validated.
- Production deployment is blocked because there is no TLS/auth edge and the shared worker role still grants `indices_all` over mixed indexes. Phase 10 must split and narrow worker identities before public exposure.

## Retention, rollover, mapping, and cursors

- Selected beta retention: raw telemetry/service map 7 days; buckets/native/normalized anomaly results 30 days; resolved incident/evidence/terminal investigations 90 days with reference-aware deletion; active cursor/registry records retained. Enforcement, disk alarms, snapshots, and measured bytes/day remain deployment blockers.
- Alias-wide logical span dedup and conflict-to-partial behavior are implemented and covered by regression tests. Physical cross-rollover replay was not forced; the staging procedure is recorded in the blocker register.
- Clean bootstrap maps worker `last_error` as the canonical strict object. The legacy local keyword cannot be changed additively; a snapshot + versioned reindex + alias migration is documented, with no destructive reset.
- Current UI has bounded first-page behavior and no pagination controls. Unsafe cursors fail closed with `400 invalid_cursor`. HMAC-signed opaque `search_after` cursors are a scale follow-up, not silently accepted tokens.
- Node 24.21.0 in the digest-pinned frontend image is authoritative. Local Node 22.17.0 is not the release runtime even though host tests/build passed.

## Phase 10 readiness

**BLOCKED.** Repair Docker/build reliability; complete current-image stack startup, genuine RCF validation, live Phase 6 and Phase 7 paths, full end-to-end/browser acceptance, restart/outage checks, least-privilege worker roles, retention enforcement, and the TLS/auth edge before EC2/public deployment.

## Phase boundary

STOP. Do not begin Phase 10 automatically.
