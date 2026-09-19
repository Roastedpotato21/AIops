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
