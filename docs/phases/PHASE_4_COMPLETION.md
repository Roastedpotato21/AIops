# Phase 4 Completion

## Outcome

**PASS** — Real application logs, distributed traces, native metrics, and
service relationships are queryable through bounded normalized backend
interfaces; replay and a scoped Collector interruption were verified without
implementing Phase 5 logic.

## Scope implemented

- Added strict normalized telemetry models and adapters for logs, spans,
  traces, native metrics, and dependency edges.
- Added TelemetryRepository.search_logs, search_spans, get_trace,
  get_native_metrics, and get_service_dependencies with bounded windows and
  sizes, deterministic ordering, explicit partial/truncated metadata, and safe
  errors.
- Added a fixed OpenSearch query client. No arbitrary DSL or new public API
  endpoint was exposed.
- Added idempotent aiops-logs and aiops-metrics-raw read aliases and
  least-privilege API-role reads while retaining native Data Prepper mappings.
- Added focused normalized mapping, trace reconstruction, dependency,
  duplicate, malformed-source, bound, partial-result, and unavailable-storage
  tests.
- Added bounded real success, real error, and Collector interruption
  verification helpers plus opt-in deterministic compatibility-probe replay.
- Added the Phase 5 input facts document and extended the telemetry field map.

No metric aggregation, p95 calculation, RCF detector, anomaly polling,
incident logic, evidence agent, remediation, dashboard page, or other Phase
5+ behavior was implemented.

## Checks run

- Compose render validation: passed.
- Bootstrap with the updated script twice: passed idempotently.
- Runtime API role reads for logs, spans, metrics, and native service map:
  HTTP 200 for all four.
- ruff check backend/app backend/tests scripts tests/integration: passed.
- Backend tests: 13 passed; two upstream Starlette/httpx deprecation warnings.
- Phase 1 persisted compatibility integration test: 1 passed.
- Phase 2–3 application tests: 17 passed; five known OpenTelemetry
  LoggingHandler deprecation warnings.
- Default compatibility probe a6f4d443304946e2839857a482b8a892:
  all six checks passed in 45.655 seconds.
- Deterministic replay probe 44444444444444444444444444444444:
  all six checks passed in 69.452 seconds.
- API /health and /ready: HTTP 200; configuration, OpenSearch, and bootstrap
  ready.
- Final Compose status: required services healthy/running; only API 8000 and
  frontend 4173 published on loopback.
- Full Phase 9 restart, persistence, browser, soak, and security suites were
  intentionally not run.

An initial backend image rebuild stalled on pinned GHCR metadata and was
stopped safely. A no-pull retry then completed from the pinned inputs. Live
verification used read-only binds while that image was pending; unit tests ran
from the frozen backend environment.

## Real telemetry evidence

Successful Order trace c62ddd3134b7c94f57644b32ce223696 returned HTTP 200 and
normalized to 17 instrumentation spans across Order, Payment, and Inventory.
The trace had a root, no missing parents, no partial state, and the expected
sibling Order→Payment and Order→Inventory branches. Each service had a
correlated normalized log for the same trace.

Controlled payment-error trace bcdc01e4f59b8f0ea994a48a4801759c returned HTTP
502 and normalized to Order and Payment spans with Order SERVER 502/ERROR and
Payment SERVER 500/ERROR status. Correlated order.payment.failed and
payment.failed ERROR logs were present. The development fault gates were
restored to disabled.

Redacted evidence is stored locally in artifacts/phase4-live.json,
artifacts/phase4-error.json, and artifacts/phase4-interruption.json.

## Service-map evidence

The native service-map index contains real POST /orders CLIENT edges:

- order-service → payment-service, destination POST /payments;
- order-service → inventory-service, destination POST /reserve.

Native field paths are recorded in the telemetry field map. The native
documents lack timestamp, trace ID, namespace, and environment, and a stale
synthetic Payment→Inventory edge can coexist under the same trace group.
Consequently the stable bounded dependency method reconstructs real,
namespace-aware relationships from span parents and returned exactly the two
approved sibling edges. This is an adapter choice within the locked
architecture, not a new dependency or schema.

## Native metric validation

For all three services, normalized native request counters were cumulative,
monotonic SUM values in {request} and duration metrics were cumulative
HISTOGRAM values in ms with 15 bounds and 16 counts. The accepted run observed
count/value 3 for each service. Persisted cumulative error counters were also
verified for all services: Inventory 1, Order 2, and Payment 1. No counter
delta or percentile was calculated.

## Measured ingestion delays

Across two real successful verification runs:

- spans: 8.662–11.432 seconds;
- correlated logs: 9.851–11.815 seconds;
- native metrics: 32.924–62.345 seconds;
- span-reconstructed dependencies: 9.948–11.867 seconds.

Native real service-map lookup took 2.434–2.635 seconds but could not be
attributed to the new request because native edge documents are timeless and
stable. A unique synthetic run proved new service-map availability within the
45.655-second total probe time. No guaranteed latency is claimed.

## Duplicate and replay findings

Two identical deterministic emissions produced exactly three native span
documents, so active-index span identity overwrote rather than doubled the
trace. Append-oriented logs and metrics produced six and 36 documents
respectively. The normalized repository collapses identical logical span IDs
across aliases and reports content conflicts as partial duplicate_conflict; it
does not claim exactly-once ingestion.

Cross-rollover physical date routing was not forced or reset. Alias-wide
normalization protects later consumers from misleading raw duplicate span
counts, but deterministic routing across a future rollover remains a Phase 9
hardening check.

## Interruption and recovery

The Collector alone was stopped. An Order request still returned 200. After
health-gated Collector restart, another Order request returned 200. The
outage-time trace 25104c55db63385c0b349b6897eb0ec0 was buffered and became
queryable, and recovery trace 8461c63d745e72f3804d6edde63393ed was queryable.
The normalized window reported zero logical duplicates, zero conflicts, and
no partial result. The Collector was restored healthy.

## Contract deviations

None. The approved Phase 3 semantics remain Order→Payment and
Order→Inventory sibling calls. The native service-map dimensional limitation
is documented explicitly; contracts and native mappings were not redesigned.

## Remaining risks

- Native service-map documents cannot independently support bounded,
  namespace-aware product queries; span reconstruction is authoritative.
- Cross-rollover deterministic physical routing has not been destructively
  forced.
- Local delays are observations, not production SLOs.
- OpenTelemetry SDK LoggingHandler and Starlette/httpx upstream deprecation
  warnings remain.
- Full restart, persistence, browser, soak, retention sizing, and security
  verification remain deferred to Phase 9.

## Phase boundary

STOP. Phase 5 requires separate authorization.
