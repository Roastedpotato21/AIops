# Phase 3 Completion

## Outcome

**PASS** — Order, Payment, and Inventory now emit real OpenTelemetry traces, correlated structured logs, and native metrics through the existing Collector and Data Prepper into OpenSearch. No Phase 4+ logic was implemented.

## Scope implemented

- `apps/telemetry/aiops_telemetry`: shared, environment-configured resource identity; bounded OTLP/gRPC trace, log, and metric exporters; FastAPI and HTTPX instrumentation; JSON console logging; request, 5xx, and duration instruments.
- `apps/order-service`, `apps/payment-service`, and `apps/inventory-service`: instrumentation around the existing Phase 2 behavior without changing business responses or dependency order.
- `apps/pyproject.toml` and `apps/uv.lock`: exact OpenTelemetry 1.44.0 / 0.65b0 dependency family.
- `apps/tests/test_telemetry.py`: real in-process HTTP propagation, resource, log-correlation, secret-exclusion, metrics, and disablement tests using in-memory exporters.
- `scripts/inspect_phase3.py`: bounded, read-only, redacted inspection of one persisted real application trace, its logs, and native metrics.
- `docker-compose.yml`: OTLP and stable resource configuration for private demo services; no additional host ports.
- `README.md`, compatibility matrix, and telemetry field map: developer commands, exact versions, units, and observed persisted paths.

No aggregation worker, RCF detector, anomaly, incident, evidence, agent, remediation, product dashboard, cloud deployment, or other Phase 4+ capability was added.

## Tests and checks

- `uv run --project apps pytest apps/tests -q`: 17 passed. Five warnings report the upstream SDK `LoggingHandler` deprecation; export behavior passed.
- `uv run --project backend ruff check scripts/inspect_phase3.py apps`: passed.
- `docker compose -f docker-compose.yml -f docker-compose.dev.yml config --quiet`: passed.
- Phase 3 demo image and tools image builds: passed.
- Payment, Inventory, and Order health checks: healthy.
- Normal request: 1 request, 1 success; connected trace and correlated logs persisted.
- Payment error: 1 request, 1 controlled failure; 500 Payment and 502 Order status/error spans plus two same-trace ERROR logs persisted.
- Payment latency: 1 request, 1 success; 750 ms injected latency produced a 753.476 ms Payment SERVER span and 757.187 ms Order→Payment CLIENT span.
- Inventory error: 1 request, 1 controlled failure; Phase 2 behavior remained operational.
- Native application metrics: request/error cumulative sums in `{request}` and duration histograms in `ms` persisted.
- `scripts/inspect_phase3.py` against the accepted normal trace: connected trace, correlated logs, and native metrics all true.
- Preserved Phase 1 compatibility probe `1e866a0876f240f9b40eae197f5b5015`: logs, counter, histogram, gauge, spans, and native service map all passed in 57.161 seconds.
- Fault routes were restored to their default disabled configuration after controlled tests.

Deadline-conscious scope deferred broad restart, persistence, browser, soak, and repeated frontend checks to Phase 9 as authorized. They were not substituted with mocked ingestion results.

## Connected trace evidence

Normal trace: `a5cdbbf1d53016d9dbf9a3d8f8f52be1`.

| Service/span | Kind | Span ID | Parent span ID | HTTP status | Duration |
|---|---|---|---|---:|---:|
| Order `POST /orders` | SERVER | `4839e0e709d6a388` | root | 200 | 124.704 ms |
| Order → Payment `POST` | CLIENT | `29259ce5f78de1f2` | `4839e0e709d6a388` | 200 | 15.612 ms |
| Payment `POST /payments` | SERVER | `51845de235e7505f` | `29259ce5f78de1f2` | 200 | 4.481 ms |
| Order → Inventory `POST` | CLIENT | `1b1e47bbc1de4e4d` | `4839e0e709d6a388` | 200 | 9.871 ms |
| Inventory `POST /reserve` | SERVER | `c6ac2189ae0d0a94` | `1b1e47bbc1de4e4d` | 200 | 5.427 ms |

This proves W3C propagation over real container HTTP boundaries. Payment and Inventory are sibling downstream calls from Order; no Payment→Inventory application dependency exists.

## Error and log-correlation evidence

Payment-error trace: `3e445e39a16ed8d4a4f3cd2175ff1ac6`.

- Order SERVER `e278741e510cdd61`: HTTP 502, status code ERROR.
- Order→Payment CLIENT `8ed4be8368bc3e36`: HTTP 500, status code ERROR.
- Payment SERVER `745dcfde28b00c0e`: HTTP 500, status code ERROR.
- Persisted Payment `payment.failed` ERROR log: same trace, span `745dcfde28b00c0e`.
- Persisted Order `order.payment.failed` ERROR log: same trace, span `e278741e510cdd61`.

Normal trace logs for `payment.completed`, `inventory.completed`, and `order.completed` also carried the matching trace and active SERVER span IDs.

## Native metric evidence

All three services persisted:

- `demo.http.server.requests`: monotonic cumulative SUM, unit `{request}`.
- `demo.http.server.duration`: HISTOGRAM with count/sum/buckets, unit `ms`.

Controlled failures additionally persisted `demo.http.server.errors` as a monotonic cumulative SUM with unit `{request}` for Order, Payment, and Inventory. Health and fault-control endpoints do not contribute to these business metrics.

## Sensitive-data check

The focused log test sent an Authorization value and distinctive payment amount, then asserted neither appeared in console logs, exported logs, or spans. Application events use fixed low-cardinality names. Credentials, request bodies, and fault scenario labels are not recorded. The live inspector prints selected IDs, status, duration, service, metric name/type/unit, and event fields only.

## Contract corrections

1. **Approved Phase 3 trace-flow clarification:** the handoff's linear diagram and test item saying Payment → Inventory conflicted with the locked Phase 2 application semantics. Per explicit approval, Phase 3 preserves Order → Payment and Order → Inventory within one trace. This is a contract wording correction, not an architecture change, and no Payment → Inventory business dependency was introduced.
2. **Deployment semantic key compatibility:** the handoff named the older scalar `deployment.environment`. The pinned semantic-convention package defines the current stable key as `deployment.environment.name`, and Phase 1 documents already established that object path in OpenSearch. Emitting the scalar caused real 400 mapping conflicts. Phase 3 therefore uses `deployment.environment.name`, records the actual path in the field map, and performs no index reset or schema redesign.

The preserved synthetic Phase 1 probe still models its original linear synthetic relationship for compatibility testing; it does not represent Phase 3 application business semantics.

## Remaining risks

- The pinned OpenTelemetry SDK warns that its SDK `LoggingHandler` is deprecated; it remains functional in 1.44.0 and all log export checks passed. Migration should occur only with a compatible pinned instrumentation release.
- Export is bounded and best-effort; temporary Collector unavailability does not provide guaranteed lossless telemetry.
- Broad restart/persistence/browser/soak coverage remains deferred to Phase 9 under the deadline-reduced verification authorization.

## Phase boundary

STOP. Phase 4 requires separate authorization.
