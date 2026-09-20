# Phase 5 Completion

## Outcome

**PARTIAL** — deterministic one-minute aggregation, replay/late-data handling, six real OpenSearch RCF detectors, controlled latency/error feature changes, and the native-result adapter are implemented. Native detectors remained in real RCF warm-up, so no positive latency or error anomaly was observed and no such result was fabricated.

## Scope implemented

- A persistent, separately credentialed aggregation worker reads `TelemetryRepository.search_spans` with an exact SERVER-kind filter, groups the three registered services, waits the configured 90-second completeness delay, writes deterministic finalized buckets, and persists per-service CAS cursors with a ten-minute replay overlap.
- Strict `aiops-service-metrics-v1` and `aiops-anomalies-v1` storage, additive bootstrap mappings, a worker security role, local ignored worker credentials, and structured failure/processing-envelope models were added.
- Six committed detector specifications and an idempotent admin provisioner create two single-entity native detectors per registered service: `latency_p95_ms` and `error_rate`, one-minute interval, three-minute delay, shingle 8, exact finalized/eligible/version/service filters, and a shared custom result index.
- A bounded CLI inspector reads buckets and native profiles, normalizes supported native results, verifies exact bucket association, and writes deterministic normalized results. It does not create incidents.
- Focused tests cover inclusion, errors, counts, p95 edges, sample quality, identity, bounded sequential outage recovery, replay, late arrival, progress, detector specs, normalization, and unavailable OpenSearch.

No incident creation, severity, correlation, evidence bundles, agent/provider integration, remediation, product UI pages, or other Phase 6+ logic was implemented.

## Tests and checks

- `uv run --project backend ruff check backend/app backend/tests scripts`: passed.
- `uv run --project backend pytest backend/tests -q`: 38 passed; two upstream Starlette/httpx deprecation warnings.
- `uv run --project apps pytest -c apps/pyproject.toml apps/tests -q`: 17 passed; five upstream OpenTelemetry logging-handler deprecation warnings.
- `docker compose -f docker-compose.yml -f docker-compose.dev.yml config --quiet`: passed.
- Phase 5 bootstrap, worker, provisioner, and inspector image builds passed; the corrected aggregation-worker image was rebuilt and restarted successfully after the final Docker Desktop restart.
- Bootstrap reran idempotently multiple times. Detector provisioning reran twice with the same six native IDs.
- API `/health` returned `ok`; `/ready` returned `ready` during the live run.
- Aggregation worker was healthy and published through its least-privilege runtime identity after the exact bulk permission was verified.
- The Collector process remained available and the live telemetry evidence was persisted, but its Docker health check was `unhealthy`: the `otelcol-contrib components` probe exceeded its five-second timeout while printing the component manifest. This is a health-probe defect, not evidence of a Collector process or OTLP pipeline failure.

## Metric-bucket evidence

Normal payment buckets included:

| UTC minute | Requests | Errors | Error rate | p95 ms | Quality |
|---|---:|---:|---:|---:|---|
| 2026-09-19 17:33 | 120 | 0 | 0.0 | 24.433023 | complete/eligible |
| 2026-09-19 17:34 | 120 | 0 | 0.0 | 7.751620 | complete/eligible |
| 2026-09-19 17:35 | 120 | 0 | 0.0 | 6.798680 | complete/eligible |
| 2026-09-19 17:36 | 119 | 0 | 0.0 | 7.552110 | complete/eligible |

Order and Inventory produced corresponding complete eligible buckets. Successful empty queries produced explicit `insufficient` buckets with null rates/latencies, distinct from healthy telemetry. Early minutes affected by a temporary pre-fix query truncation remained frozen and were annotated `partial` plus `late_data`; they were not rewritten into detector-ready history.

## p95 and error-rate validation

The implemented deterministic percentile is nearest rank: sort eligible durations in milliseconds and select `ceil(0.95 * n)`. Tests cover zero, one, repeated equal, 19/20 minimum-sample, and highly skewed inputs.

- Normal payment p95: primarily 6.799–24.433 ms in the accepted baseline examples.
- Controlled payment-latency load: 77 successful requests over 60.227 seconds, 780.410 ms observed average; finalized payment buckets reached 753.550501 ms (29 requests) and 754.885456 ms (68 requests), both complete/eligible.
- Controlled payment-error load: 120 requests, 120 expected failures over 59.528 seconds; finalized payment buckets were 25/25 and 94/94 errors, both error_rate 1.0 and complete/eligible.
- Fault routes were restored to their default disabled configuration after both scenarios.

## Aggregation replay result

Unit replay writes one logical deterministic ID even when recomputation timestamps change. Live ten-minute overlap re-queries returned existing IDs and updated them without duplicate logical buckets. Feature values and finalization eligibility remain frozen after finalization; newly discovered spans update only late-count/quality annotations. Cursor persistence occurs only after bucket publication. A long-outage regression test proves the worker advances sequentially in bounded ten-minute forward batches while retaining the ten-minute replay overlap, rather than skipping directly to the newest window.

## RCF detector state

Six real detectors were provisioned and started. Consecutive provisioner runs returned the same IDs:

- Order latency `oni9uqABewDwCa_DiR8P`; errors `uHi9uqABewDwCa_DlR_Z`.
- Payment latency `xXi9uqABewDwCa_DmR_E`; errors `0ni9uqABewDwCa_DnR_y`.
- Inventory latency `33i9uqABewDwCa_DoR_4`; errors `1ni9uqABewDwCa_DpiAM`.

The payment profiles were genuinely `INIT`, 0%, estimated 32 minutes, with 32 needed shingles. When current eligible input stopped, the plugin reported no data in the current window; the product projection maps that condition to `insufficient_data`, not healthy or ready.

## Real latency anomaly result

Not observed. The real latency scenario materially changed the detector feature from the normal range to approximately 754 ms, but the native RCF model was still warming. No positive result was inserted or fabricated.

## Real error anomaly result

Not observed. The real error scenario changed payment error_rate from 0.0 to 1.0 in two eligible finalized buckets, but the native RCF model was still warming. No positive result was inserted or fabricated.

## Warm-up and data-quality findings

- Native OpenSearch 3.8 warm-up was longer than the eight configured input shingle: the profile explicitly requested 32 initialization shingles and estimated 32 minutes.
- Normal traffic created correct complete/eligible data after the SERVER-kind source filter prevented unrelated CLIENT spans from exhausting the normalized query bound.
- Historical pre-fix partial buckets stayed partial and ineligible as required by immutable-finalization semantics.
- Native results became available during warm-up and exercised the real result query/adapter/write path. The strict normalized write caught a missing additive mapping update; source now applies the canonical nested processing mapping to existing indexes before normalization. The final live inspector exited successfully and the normalized index contained 136 deterministic results, all `failed` with null grade/confidence because the native source results explicitly reported no data in their current windows; each retained its exact input bucket ID. These are operational detector results, not positive anomalies.

## Contract deviations

1. Phase 0 specifies OpenSearch TDigest compression 100 for p95, while the Phase 5 handoff requires a deterministic documented percentile. This implementation follows the later handoff with nearest-rank p95; it is not claimed equivalent to TDigest and requires explicit contract reconciliation.
2. Phase 0's detector-name formula containing the full 68-character service ID exceeds OpenSearch 3.8's enforced 64-character detector-name limit. Names use the unique registered service name (`aiops-payment-service-latency-v1`, for example); the full deterministic service ID remains in the registry key and exact detector filter.
3. Where the handoff says `insufficient_data` for bucket quality and `created_at`, the authoritative Phase 0 domain model uses `quality_status=insufficient` and `computed_at`/`finalized_at`; the implementation preserves Phase 0 spelling. Detector status still uses `insufficient_data`.
4. A pre-correction local development bootstrap mapped `aiops-worker-state-v1.last_error` as keyword. Clean bootstrap source now creates the required structured Failure object and preserves the existing local volume non-destructively; writing a non-null structured worker failure to that legacy local index remains a local migration blocker.

## Remaining blocker

Phase 5 cannot be marked PASS until sustained eligible baseline traffic completes native RCF initialization and real positive latency/error anomaly results are observed and normalized. The additive `processing` mapping and normalized write were verified on the preserved volume; the principal blocker is native model warm-up and positive-result evidence. The Collector's over-expensive Docker health probe also needs a narrow correction in the authorized hardening scope. No incident logic should begin before these Phase 5 checks are complete.

## Phase boundary

STOP. Do not begin Phase 6 automatically.
