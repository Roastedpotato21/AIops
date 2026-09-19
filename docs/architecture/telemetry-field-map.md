# Phase 1 Telemetry Field Map

Observed from compatibility probe `297cc61e42cf458583c64cf405595b30` on 2026-09-19. These paths describe persisted Data Prepper output, not a later product schema.

| Signal | Semantic value | Persisted field path | Observed value |
|---|---|---|---|
| All | probe namespace | `resource.attributes.service.namespace` | `compatibility-probe` |
| All | service name | `resource.attributes.service.name` | `order-service`, `payment-service`, `inventory-service` |
| All | unique probe run | `resource.attributes.aiops.probe.run_id` | 32-character run ID |
| Log | event body | `body` | `compatibility probe event` |
| Log | severity | `severityText` | `INFO` |
| Log | event time | `time` | RFC 3339 nanosecond timestamp |
| Metric | name/type/unit | `name`, `kind`, `unit` | SUM `{request}`, HISTOGRAM `ms`, GAUGE `1` |
| Metric | counter value | `value`, `isMonotonic`, `aggregationTemporality` | `1.0`, `true`, cumulative |
| Metric | histogram | `count`, `sum`, `min`, `max`, `buckets[]` | `1`, `12.5`, `12.5`, `12.5`, 10–25 ms bucket count `1` |
| Metric | gauge value | `value` | `1.0` |
| Trace | identity | `traceId`, `spanId`, `parentSpanId` | one trace; root → payment → inventory parent chain |
| Trace | operation | `name`, `attributes.http.route` | run-scoped name plus `/orders`, `/payments`, `/inventory/reserve` |
| Trace | service | `serviceName` | native top-level Data Prepper field |
| Service map | edge | `serviceName`, `destination.domain` | `order-service` → `payment-service`; `payment-service` → `inventory-service` |
| Service map | run-scoped trace group | `traceGroupName` | contains `compatibility-probe <run_id>` |

Native Data Prepper ownership is preserved for the trace and service-map indices. The exact 2.16.0 native span template used during bootstrap is committed at `infra/opensearch/otel-v1-apm-span-index-standard-template.json`.

## Phase 3 real application telemetry

Observed from normal application trace `a5cdbbf1d53016d9dbf9a3d8f8f52be1` on 2026-09-19.

| Signal | Semantic value | Persisted field path | Observed value |
|---|---|---|---|
| All | application namespace | `resource.attributes.service.namespace` | `demo-shop` |
| All | service version | `resource.attributes.service.version` | `0.3.0` |
| All | environment | `resource.attributes.deployment.environment.name` | `development` |
| Trace | W3C trace identity | `traceId`, `spanId`, `parentSpanId` | Order root with sibling Payment and Inventory client/server branches |
| Trace | span kind | `kind` | `SPAN_KIND_SERVER`, `SPAN_KIND_CLIENT` |
| Trace | HTTP fields | `attributes.http.method`, `attributes.http.route`, `attributes.http.status_code` | `POST`, business route, 200/500/502 |
| Trace | duration | `durationInNanos` | native nanoseconds; converted to milliseconds only for inspection output |
| Log | correlation | `traceId`, `spanId` | active application span IDs |
| Log | event | `body`, `severityText` | fixed low-cardinality event names and INFO/ERROR |
| Metric | completed request count | `name`, `value`, `unit` | `demo.http.server.requests`, cumulative SUM, `{request}` |
| Metric | 5xx count | `name`, `value`, `unit` | `demo.http.server.errors`, cumulative SUM, `{request}` |
| Metric | duration | `name`, `count`, `sum`, `buckets[]`, `unit` | `demo.http.server.duration`, HISTOGRAM, `ms` |

The application emits the current stable semantic-convention key `deployment.environment.name`. This also preserves compatibility with the object mapping established by the Phase 1 probe; the older scalar `deployment.environment` cannot coexist at the same OpenSearch path.

## Phase 4 normalized read boundary

Verified on 2026-09-19 with real application trace
c62ddd3134b7c94f57644b32ce223696. Product code reads the normalized models in
backend/app/models/telemetry.py through TelemetryRepository; the raw paths
below are private adapter inputs.

| Normalized value | Native persisted path |
|---|---|
| service namespace | resource.attributes.service.namespace |
| deployment environment | resource.attributes.deployment.environment.name |
| service name / instance / version | resource.attributes.service.name, resource.attributes.service.instance.id, resource.attributes.service.version |
| trace / span / parent identity | traceId, spanId, parentSpanId |
| span operation / kind | name, kind |
| span start / completion | startTime, endTime |
| span duration | durationInNanos |
| span status | status.code, attributes.http.status_code, or attributes.http.response.status_code |
| log event / severity / correlation | time, observedTimestamp, body, severityText, traceId, spanId |
| metric identity / sample time | name, kind, unit, time, startTime |
| sum semantics | value, isMonotonic, aggregationTemporality |
| histogram semantics | count, sum, min, max, explicitBounds, bucketCountsList, buckets[] |
| native dependency source | serviceName |
| native dependency target | destination.domain, destination.resource |
| native dependency span kind / group | kind, traceGroupName, hashId |

The real native service map contains order-service → payment-service with
destination resource POST /payments and order-service → inventory-service
with destination resource POST /reserve, both under trace group POST /orders.

The native service-map documents contain no timestamp, trace ID, namespace, or
environment. A stale synthetic payment-service → inventory-service document
can therefore coexist under the same trace-group name and cannot be safely
assigned to a real application window. get_service_dependencies consequently
reconstructs bounded, namespace-aware edges from normalized CLIENT→SERVER
parent links. Native service-map documents remain compatibility evidence, not
the source of windowed product dependency queries.
