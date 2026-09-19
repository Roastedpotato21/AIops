# AIOps Phase 0 contract package

Status: proposed implementation contracts for approval. Architecture: approved and locked. Contract version: `1.0.0`. Prepared: 2026-09-19.

This package contains documentation only. It does not implement Phase 1, create application code, select unverified dependency versions, authenticate services, change Git identity, or publish a repository.

## Read in this order

1. [Domain schemas](../../contracts/domain.md): common types, every domain field, identifiers, lifecycle records.
2. [Processing contracts](../../contracts/processing.md): aggregation, RCF, incident rules, replay, recovery, evidence selection.
3. [Agent contracts](../../contracts/agent.md): investigator/provider boundaries, tools, budgets, report validation.
4. [API contracts](../../contracts/api.md): Pydantic-compatible request/response shapes and HTTP behavior.
5. [OpenSearch contracts](../../contracts/storage.md): aliases, mappings, ownership, retention, consistency.
6. [Repository and compatibility](repository-and-compatibility.md): module ownership and checks before implementation.
7. [PHASE 1 HANDOFF FOR SOL MEDIUM](../phases/PHASE_1_HANDOFF_FOR_SOL_MEDIUM.md): bounded next-phase instructions.

## Locked flow

Applications → OTel SDKs → Collector → Data Prepper → OpenSearch logs, native metrics, spans, service relationships.

Completed SERVER spans → aggregation worker → one-minute service feature buckets → OpenSearch RCF latency/error detectors → native results → deterministic incident worker → incidents and evidence → separate investigation worker → read-only agent → evidence-backed reports → FastAPI → React/TypeScript/Vite.

Local and eventual EC2 deployment use Docker Compose. OpenSearch is the only application datastore. Native metrics corroborate; logs are evidence. No autonomous actions. Fault injection is demo/development-only. Ingestion, storage, and administration interfaces remain private.

## Contract decisions requiring approval, not architectural changes

| Decision | Exact v1 choice | Where specified |
|---|---|---|
| Identity | Namespace + environment + service name; full SHA-256 deterministic IDs | Domain |
| Aggregation | UTC minute windows; server completion time; minimum 20 eligible requests; 90-second lateness allowance | Processing |
| Detection | Two single-feature detectors/service; 60-second interval; 180-second delay; native positive grade, no invented grade/confidence cutoff | Processing |
| Incidents | One active episode per service and feature; first eligible positive RCF result opens; cross-service links do not merge episodes | Processing |
| Severity | Explicit observed-impact policy, distinct from RCF grade/confidence | Processing |
| Recovery | Frozen pre-incident baseline; 3 healthy minutes to recovering, 5 to resolved; stale data blocks progress | Processing |
| Evidence | Typed, redacted snapshots; 256 KiB/item, 2 MiB/bundle; immutable bundles; bounded run additions | Processing and agent |
| Jobs | Stored in OpenSearch; one incident writer; conditional claims on investigation documents; at-least-once execution | Processing and storage |
| API | UTC times, typed envelopes, opaque cursors, `202` persisted investigation requests | API |
| Versions | Exact values marked VERIFY BEFORE IMPLEMENTATION; pin verified versions and image digests before merge | Repository and compatibility |

These operational constants are versioned policies, not claims of calibrated anomaly accuracy or measured performance. Phase 5 evaluates their fitness; changing them requires an explicit contract revision with tests.

## Phase boundaries

Phase 0 supplies contracts. Phase 1 supplies only scaffold, shells, infrastructure, health/readiness, bootstrap foundations, and a synthetic OTLP compatibility probe. It must not implement detectors, demo business services, instrumentation, incidents, agents, dashboard feature pages, or EC2 deployment.

No concrete contradiction requiring an architecture redesign was found. Compatibility verification remains a gate: documentation describes supported capabilities, not a tested release combination.

## Sources and verification limits

Official references checked for contract design:

- [Data Prepper OTLP source](https://docs.opensearch.org/latest/data-prepper/pipelines/configuration/sources/otlp-source/): signal routing and output-format choices must match processors.
- [Trace analytics](https://docs.opensearch.org/latest/data-prepper/common-use-cases/trace-analytics/): native trace and service-map mappings remain owned by Data Prepper.
- [AD API](https://docs.opensearch.org/latest/observing-your-data/ad/api/): detector creation, profiles, and result retrieval use plugin interfaces.
- [AD configuration](https://docs.opensearch.org/latest/observing-your-data/ad/index/): warm-up, delay, and custom result indexes are release-sensitive.
- [Anomaly polling guidance](https://docs.opensearch.org/latest/observing-your-data/ad/managing-anomalies/): execution time and overlap matter for delayed results.
- [OpenSearch conditional updates](https://docs.opensearch.org/latest/api-reference/document-apis/update-document/): document-level optimistic concurrency, not cross-document transactions.
- [Collector resilience](https://opentelemetry.io/docs/collector/resiliency/) and [Data Prepper buffers](https://docs.opensearch.org/latest/data-prepper/pipelines/configuration/buffers/buffers/): persistent Collector queues do not prove end-to-end losslessness.

No runtime compatibility tests were run in Phase 0. Follow the compatibility checklist before claiming a working stack.
