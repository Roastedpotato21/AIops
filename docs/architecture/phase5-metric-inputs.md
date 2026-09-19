# Phase 5 Metric Inputs

This document records only Phase 4 facts verified against the pinned local
stack. It does not define or implement aggregation, percentile calculation, or
detector behavior.

## Completed span input

Phase 5 must consume TelemetryRepository.search_spans, not native OpenSearch
documents. The private adapter currently reads:

- completion time from endTime (date_nanos);
- start time from startTime (date_nanos);
- duration from durationInNanos, converted to milliseconds by dividing by
  1,000,000;
- span kind from kind; completed request candidates are SPAN_KIND_SERVER;
- service identity from resource.attributes.service.namespace,
  resource.attributes.deployment.environment.name,
  resource.attributes.service.name, and
  resource.attributes.service.instance.id;
- trace identity from traceId, spanId, and parentSpanId;
- error status from status.code equal to 2 or an HTTP status of at least 500
  in attributes.http.status_code or
  attributes.http.response.status_code.

Use half-open completion windows: window_start <= endTime < window_end.
Do not window on start time. Preserve the normalized service namespace,
environment, and name as the aggregation key. Do not count CLIENT or INTERNAL
spans as completed service requests.

## Native metric evidence

The three real services persisted:

| Metric | Native type | Unit | Temporality | Verified structure |
|---|---|---|---|---|
| demo.http.server.requests | SUM | {request} | cumulative | monotonic scalar value |
| demo.http.server.errors | SUM | {request} | cumulative | monotonic scalar value |
| demo.http.server.duration | HISTOGRAM | ms | cumulative | count, sum, min, max, 15 explicit bounds and 16 bucket counts |

These are native cumulative instruments. Phase 5 must not treat a stored
counter value as an interval count without a separately specified reset-aware
delta algorithm. Phase 4 did not calculate p95.

## Delay and completeness observations

Two real successful Order verification runs observed:

- spans queryable after 8.662–11.432 seconds;
- correlated logs queryable after 9.851–11.815 seconds;
- native metrics queryable after 32.924–62.345 seconds;
- span-reconstructed dependencies queryable after 9.948–11.867 seconds.

The real native service-map edges already existed and their schema has no event
time or trace ID, so the 2.434–2.635 second lookup time is not attributable to
the triggering request. A unique synthetic compatibility run made its service
map and all other signals queryable within 45.655 seconds; the deterministic
two-emission replay completed in 69.452 seconds. These are practical local
observations, not latency guarantees.

Phase 5 must use a configurable completeness delay and test late arrival. The
observed metric maximum of 62.345 seconds is the minimum evidence available for
choosing a local default; production behavior remains unmeasured.

## Replay and query behavior

The deterministic probe emitted the same three trace/span identities twice.
The native trace alias returned exactly three span documents, demonstrating
overwrite/idempotent identity in the active write index. Logs and metrics are
append-oriented and returned six log and 36 metric documents for the two
emissions. Exactly-once ingestion is not claimed.

TelemetryRepository additionally collapses identical logical spans across all
indices by namespace, environment, trace ID, and span ID. Conflicting
duplicates keep the first deterministic source ordering and mark the result
partial with duplicate_conflict; malformed spans are excluded and reported.
Cross-rollover physical routing was not forced because doing so would mutate
native index ownership. Phase 5 must continue querying through this alias-wide
normalized boundary rather than counting raw hits.

## Dependency input

The verified real relationships are Order → Payment and Order → Inventory, as
sibling branches in one trace. There is no real Payment → Inventory
dependency. Windowed dependency queries reconstruct CLIENT→SERVER parent links
from normalized spans because native service-map documents lack the time and
tenant dimensions needed for a bounded product query.

## Retention candidate

No retention deletion policy was introduced in Phase 4. The read aliases
aiops-logs, aiops-metrics-raw, and otel-v1-apm-span are the stable boundary for
a future reviewed retention policy. Retention sizing and deletion remain a
Phase 9 hardening decision; Phase 5 must not assume unlimited history.
