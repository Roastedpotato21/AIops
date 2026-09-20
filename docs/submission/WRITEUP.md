# OpenSearch AIOps — Hackathon Write-up

## Problem

Telemetry volume is not the same as operational understanding. A service team can have traces, logs, and metrics yet still spend the first minutes of an incident deciding what changed, how severe it is, which evidence is trustworthy, and whether an automated explanation has overreached.

The project addresses that gap with an evidence-first AIOps beta. It detects service-level changes, creates deterministic operational episodes, preserves the exact evidence used, and allows a bounded read-only investigator to summarize what is known and what remains unknown.

## Solution

Three instrumented demo services model a real request path: Order calls Payment and Inventory within one W3C trace. OpenTelemetry sends traces, correlated logs, and native metrics through the Collector and Data Prepper.

A persistent worker reads completed server spans and creates deterministic one-minute p95-latency and error-rate buckets. Six native OpenSearch RCF detectors score those eligible buckets. Their results are normalized without changing native grade or confidence.

The deterministic incident engine then:

- maintains one active episode per service, feature, and policy version;
- freezes a pre-incident baseline;
- calculates impact severity independently from model confidence;
- requires three consecutive healthy minutes to recover and five to resolve;
- correlates incidents only with stored trace/dependency evidence;
- creates immutable, redacted, bounded evidence bundles.

A separate investigation worker claims persisted jobs and runs an interchangeable reasoning provider. The host exposes exactly seven typed read-only tools and validates scope, time, result size, evidence citations, cost/tokens, and deadline. Suggested actions are advice only and always carry `executed=false`.

FastAPI serves typed operational views to a React/Vite dashboard for overview, services, one-minute metrics, dependencies, incidents, evidence, and investigation results.

## How OpenSearch is used

OpenSearch is the only application datastore and the center of the design:

- Data Prepper writes logs, raw metrics, native traces, and native service relationships.
- Application-owned strict indexes store service feature buckets, normalized anomalies, incidents, evidence, investigations, and durable worker state.
- The native anomaly detection plugin runs the Random Cut Forest models.
- Conditional sequence/primary-term updates fence mutable claims and job leases.
- Deterministic document IDs make replays idempotent.
- Security roles isolate ingestion, aggregation, incident, investigation, API, and administrative ownership.
- APIs and agent tools use bounded trusted query templates; clients never submit arbitrary OpenSearch DSL.

The implementation preserves native Data Prepper mappings and records the verified field adapter in `docs/architecture/telemetry-field-map.md`.

## AWS deployment story

The local beta is packaged with Docker Compose and has passed controlled restart, persistence, least-privilege, and OpenSearch outage/recovery checks. Phase 10 will deploy the same component boundaries to AWS rather than redesigning them.

The deployment gate includes:

- one TLS-terminating authenticated edge for the frontend and API;
- private OpenSearch, OTLP, Data Prepper, worker, and demo-service interfaces;
- secret-backed credentials and verified TLS;
- request-size and rate limits;
- 7/30/90-day retention enforcement with reference-aware product cleanup;
- snapshots and disk alarms;
- a versioned migration if the preserved legacy development volume is reused;
- bounded performance and storage measurement on the chosen EC2 shape.

Final EC2 URL: `<PHASE_10_URL_PENDING>`

No AWS deployment is claimed in the current repository state.

## Validation

Accepted evidence includes:

- a real connected multi-service trace with correlated logs and native metrics;
- deterministic one-minute bucket generation and controlled latency/error feature changes;
- six native OpenSearch detectors and genuine native profile state;
- live least-privilege reads/writes with forbidden writes returning 403;
- a persisted, clearly fixture-labeled incident with 33 evidence items;
- a persisted succeeded investigation that abstains from unsupported causality;
- containerized React/API browser verification with no console or network errors;
- one full restart and one OpenSearch outage/recovery without duplicate product records.

The six RCF detectors were still in native `INIT`, so no positive latency/error anomaly or complete telemetry-to-dashboard anomaly chain is claimed. The fixture demonstrates only the downstream deterministic product path.

## Challenges and learning

### Native model warm-up

The selected OpenSearch release required more initialization data than the configured shingle size suggested. The correct response was to expose `INIT` and keep traffic available—not change detector semantics or fabricate history.

### Replay and consistency

OpenSearch does not provide cross-index transactions. Deterministic IDs, create/CAS operations, durable processing envelopes, overlap scans, and reconciliation make every step safely repeatable.

### Evidence before explanation

Free-form model output is not operational truth. The strongest design decision was to persist bounded evidence first, pin an immutable bundle to a job, and reject any report that cites evidence outside that authorized set.

### Infrastructure recovery

A Docker Desktop data-VHD failure was diagnosed and repaired without pruning or deleting volumes. That reinforced the value of persistence tests, diagnostic evidence, and controlled recovery over destructive resets.

### Separation of concerns

Native RCF detects unusual feature values. Deterministic code owns incident identity, severity, lifecycle, and recovery. A read-only agent interprets evidence but cannot mutate the operational record or execute a fix. Keeping these roles separate makes uncertainty honest and failures containable.

## AI coding tools

OpenAI Codex assisted with implementation, focused test generation, debugging, repository inspection, and documentation. AI-generated suggestions were constrained by approved architecture contracts and accepted only after deterministic tests or live evidence. No generated narrative was used as a substitute for runtime verification.

## Open-source credits

The project builds on OpenSearch and its anomaly-detection/security plugins, OpenSearch Data Prepper, OpenTelemetry, FastAPI, Pydantic, HTTPX, React, Vite, Recharts, Pytest, Ruff, Vitest, and Testing Library. Exact versions are pinned in container references and lockfiles and summarized in the compatibility matrix.

## Tracks

- **Build It:** an end-to-end OpenSearch-centered AIOps product with deterministic incidents and safe evidence-backed investigations.
- **Ship It:** a reproducible Compose deployment that has passed local persistence and resilience checks and is prepared for the Phase 10 AWS security/deployment gate.
