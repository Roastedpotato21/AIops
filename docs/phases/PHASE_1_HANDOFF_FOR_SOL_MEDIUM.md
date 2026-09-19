# PHASE 1 HANDOFF FOR SOL MEDIUM

## Objective

Implement only the AIOps repository scaffold, backend/frontend shells, local Docker Compose infrastructure, health/readiness foundations, bootstrap/configuration layout, and a repeatable synthetic OTLP compatibility probe. Stop at the Phase1 acceptance boundary and report results. Do not implement later phases.

Architecture is locked: Applications → OTel SDK → Collector → Data Prepper → OpenSearch; later metric aggregation → RCF → deterministic incident worker → separate read-only investigation worker → FastAPI → React/TypeScript/Vite. OpenSearch is the only application datastore. No architecture redesign without a concrete blocking contradiction.

## Required reading

- [Phase0 index](../architecture/PHASE_0_CONTRACTS.md).
- [Repository and compatibility](../architecture/repository-and-compatibility.md), especially verification checklist and version policy.
- [API](../../contracts/api.md): implement **only** /health and /ready; preserve the later API boundary.
- [Storage](../../contracts/storage.md): bootstrap marker, private credentials, native mapping ownership, probe-only scope.
- [Processing](../../contracts/processing.md): understand span identity and metric meaning; do **not** implement aggregation or detectors.

Do not implement every domain model simply because its contract exists. Phase1 types are configuration, probes, bootstrap state, and probe validation only. Contract changes require explicit documentation; report a concrete inconsistency rather than silently selecting a different interpretation.

## Allowed files

| Path | Permitted work |
|---|---|
| README.md, .gitignore, .dockerignore, .env.example | Setup, ignore rules, non-secret placeholders, documented commands |
| docker-compose.yml, docker-compose.dev.yml | Local stack and explicit development-only overrides; no prod/EC2 configuration |
| backend/pyproject.toml, backend/uv.lock, backend/Dockerfile | Pinned dependencies, reproducible image, probe test dependencies |
| backend/app/main.py, config.py, api/health.py, models/health.py, opensearch/client.py | Application factory, validated env, liveness/readiness and client lifecycle only |
| backend/app/api, incidents, detection, telemetry, telemetry/aggregation, correlation, agent, opensearch, repositories, workers, models | Package markers/brief ownership documentation only except explicitly allowed shell files |
| backend/tests/ | Configuration and health/readiness tests using appropriate isolated test doubles |
| frontend/ | Minimal React/TS/Vite shell, API health/readiness display, lockfile, shell tests, build/lint/type configuration; no product feature pages |
| apps/order-service, payment-service, inventory-service, load-generator | README/placeholders only; no runnable service/load code |
| infra/otel, infra/data-prepper, infra/opensearch | Configs needed for real three-signal synthetic compatibility probe, native service map, roles/templates/bootstrap marker |
| infra/proxy | Ownership README only unless a minimal local static-serving proxy is needed by frontend image; no cloud TLS/deployment work |
| scripts/, tests/fixtures/otlp/, tests/integration/ | Version/compatibility/bootstrap/probe/verification helpers and clearly labeled synthetic protocol fixtures |
| tests/e2e/ | Ownership README/placeholders only |
| docs/architecture/compatibility-matrix.md, telemetry-field-map.md | Exact tested versions/digests, official references, actual field paths and units, compatibility results |
| docs/phases/PHASE_1_COMPLETION.md | Completion report in exact format below |
| contracts/ and existing architecture docs | Read-only by default; necessary corrections proposed and recorded, never unannounced redesign |

Preserve any existing user edits. Do not create an extra nested repository. Do not change global Git configuration, authenticate accounts, create GitHub repositories, push, or publish images as part of this phase. When a future publishing request is authorized, verify repository-local identity and the remote owner are Roastedpotato21.

## Required components and boundaries

| Compose service | Requirement |
|---|---|
| opensearch | Pinned version/digest; single node; persistent volume; security enabled; heap/host prerequisites documented; no public9200/9300 |
| opensearch-dashboards | Same exact version as OpenSearch; authenticated connection; private administration service; optional127.0.0.1:5601 development binding |
| data-prepper | Pinned image; selected OTLP source; separate signal routing; native trace/service-map processor compatibility; bounded resources; private source/control ports |
| otel-collector | Pinned contrib distribution; OTLP receiver, memory_limiter, batch, exporter, health_check and file_storage capability; private4317/4318; persistent exporter queue volume |
| api | FastAPI shell; /health and /ready; no worker startup; private service port8000 with127.0.0.1:8000 development override |
| frontend | React+TS+Vite shell served on127.0.0.1:4173 for development verification; shows actual probe status; production-style static build tested |
| bootstrap | Idempotent one-shot job; only needed probe mappings/native templates/roles and `platform-bootstrap-v1` marker; fail clearly on incompatible mapping; no index reset |
| compatibility-probe | Tools-profile one-shot service; emits protocol fixtures through Collector and verifies actual persisted signals and service map; no SDK-instrumented app |

Use named Compose networks separating internal storage/ingestion from the UI/API boundary. Only named frontend/API entry points are exposed locally; all bindings loopback. A container listening0.0.0.0 internally is not equivalent to a published host port; inspect rendered host mappings. No worker processes, detector jobs, or external LLM connectivity.

Secrets come from local ignored env/secret files or supported Docker secret mounts. Confirm Data Prepper config interpolation behavior for the pinned release; do not assume Compose substitutes variables inside bind-mounted YAML. If rendering is needed, render safely inside the container/tmp secret area, never into tracked files or logs.

## Contracts to preserve

- Health/readiness exact shapes from api.md; /health has no dependency calls; /ready fails when config/OpenSearch/bootstrap is unavailable and recovers when restored.
- Probes and fixtures are clearly synthetic, tagged compatibility-probe, and never masquerade as a working product or real detected incident.
- No arbitrary DSL browser endpoint, model tools, placeholder incident responses, or fake investigation findings.
- Preserve native Data Prepper trace/service-map mappings; commit actual field-path adapter manifest from observed probe documents.
- Span identity/replay rules must be tested as far as supported by this minimal pipeline; unresolved cross-date or conflict behavior is a Phase4 blocker, not an asserted guarantee.
- All dependency/runtime selections meet the version policy and are pinned. Do not use latest tags, unlocked dependency installs, skipped engine checks, or disable TLS verification without an explicit local-only documented configuration.
- API/worker separation and module ownership remain intact. Health shell may use async client calls or properly offload a synchronous OpenSearch client.

## Acceptance criteria

1. Setup works from a clean source checkout with documented Docker prerequisites and locally supplied secrets; no GitHub/AWS/LLM login needed.
2. Exact selected versions/digests and test evidence are recorded in compatibility-matrix.md; matching OpenSearch/Dashboards; AD plugin presence verified without creating a detector.
3. Compose validates and starts the required services in a reproducible order using health checks/retries; containers persist required data across restart.
4. Bootstrap succeeds twice without destructive resets or duplicate initialization; marker is readable by the API runtime role.
5. Synthetic trace/log/native gauge+counter+histogram fixtures travel through Collector and Data Prepper into OpenSearch. Verify values/units/identity/trace parentage and native service-map relationships. Stored fixtures are isolated by probe namespace and clearly labeled.
6. Probe has a bounded deadline (default180s, configurable up to300s for service-map processing), unique run IDs, deterministic checks, nonzero failure exit, and useful redacted diagnostics. No fixed sleeps as a substitute for readiness conditions.
7. /health returns200 while OpenSearch is stopped; /ready returns503 with safe reason then200 after recovery. Credential failure is tested without printing secrets.
8. Frontend renders the actual API state, handles unavailable API, builds and typechecks. Verify it visually in a browser and record console/network errors; do not call visual verification passed if no browser was available.
9. Unit/integration/lint/type/build commands pass; no secrets in source, fixtures, rendered logs or reports. Compose render inspection confirms only loopback expected ports.
10. Completion report separates passed, failed, and not-run checks, and enumerates later-phase blockers. Stop after Phase1.

## Commands/tests to implement and run

Commands below are the required developer interface. Create the referenced small helpers/tests in allowed paths, then execute them; they do not exist in Phase0. Use the same file flags for every Compose invocation. Run from repository root unless noted. Configuration validation output must not leak interpolated secrets: use `config --quiet`, and have port/security inspection parse rendered config in memory and print only a safe summary.

```text
docker version
docker compose version
docker compose -f docker-compose.yml -f docker-compose.dev.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.dev.yml build api frontend compatibility-probe
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d opensearch
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile tools run --rm bootstrap
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile tools run --rm bootstrap
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile tools run --rm compatibility-probe
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps

uv sync --project backend --frozen --all-extras
uv run --project backend ruff check backend/app backend/tests scripts tests/integration
uv run --project backend pytest backend/tests
uv run --project backend pytest tests/integration/test_phase1_compatibility.py
uv run --project backend python scripts/verify_phase1.py
```

Run inside frontend:

```text
npm ci
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

`verify_phase1.py` must check safe rendered-port summary, authenticated version/plugin inspection, bootstrap idempotence, HTTP probes, controlled OpenSearch stop/restart readiness transition, and persistence. It may only stop/restart this Compose project's named opensearch service, must restore it in finally/error handling, and must never delete volumes or unrelated containers. Integration test and probe can reuse one fixture run's ID instead of redundantly replaying the entire stack for every assertion.

Browser verification: visit http://127.0.0.1:4173, confirm shell renders live /health and /ready responses, inspect console/network, capture a local screenshot if available. Follow applicable browser-verification skills in the implementation session. Test failure state through the scoped outage check, not fake incident content.

If commands fail because Docker/network/host permission is unavailable, record exact blocker and safe diagnostics. Do not substitute a mocked ingestion pass. Do not run docker compose down -v or prune. Leave the stack available for review unless the user requests shutdown.

## Non-goals

No demo microservice implementation, traffic generator, application SDK instrumentation, feature aggregation, RCF detector creation/start, anomaly polling, incident logic, evidence collection product logic, investigator/provider integration, feature dashboard pages, fault endpoints, EC2 provisioning/deployment, GitHub publishing, registry publishing, Kubernetes, Kafka, Redis, SQL database, or autonomous actions.

Bootstrap creates only prerequisites for this phase's compatibility checks, not the full later product schema. Placeholder directories are permitted; placeholder behavior that suggests later phases work is not.

## Credentials

Notify the user before a step actually requires external credentials. Local OpenSearch/bootstrap/runtime credentials are required for this phase: user-supplied or locally generated into ignored secret files, never committed or printed. `.env.example` contains placeholders only. Do not default to a known admin password. Public image/dependency downloads normally need no login; registry rate limits/private artifacts may require a separate user decision. GitHub, Docker Hub authentication, AWS and LLM credentials are not prerequisites for the intended Phase1 scope; never authenticate them automatically.

## Exact completion report format

Write docs/phases/PHASE_1_COMPLETION.md and provide a concise user-facing summary using this order:

1. **Outcome:** PASS / PARTIAL / BLOCKED; one sentence describing what actually works.
2. **Scope implemented:** changed paths and purpose; explicit confirmation no later-phase product logic was implemented.
3. **Version matrix:** component, exact version, image digest/lock reference, official source, verification date.
4. **Commands executed:** command, exit status, observed result; separate NOT RUN with reason. Redact credentials.
5. **Compatibility evidence:** probe run ID; real persisted trace/log/metric examples or artifact paths; verified service edges; field-map manifest link; measured ingestion time.
6. **Health and persistence:** startup, bootstrap rerun, readiness outage/recovery, restart persistence results.
7. **Frontend verification:** URL, visible behavior, console/network result, screenshot path or explicit unavailable status.
8. **Exposure and secrets:** actual published loopback ports, private ports, role/TLS status, secret handling; no secret values.
9. **Contract deviations:** none, or exact contract location, concrete issue, proposed narrow amendment; no silent redesign.
10. **Remaining risks/blockers:** include replay/date-routing/acknowledgment checks deferred to Phase4 and any failing acceptance criterion.
11. **Next authorized phase:** STOP. Phase2 requires a separate handoff/authorization; do not begin it automatically.
