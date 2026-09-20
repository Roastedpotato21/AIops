# AIOps platform

Phase 1 establishes the platform shell and local telemetry infrastructure. Phase 2 adds a controlled demo request chain—Order calls Payment and then Inventory—and a profile-only load generator. Phase 3 adds real OpenTelemetry tracing, correlated JSON logs, and native request metrics to those services. Phase 4 provides bounded normalized telemetry reads. Phase 5 derives finalized one-minute service buckets and feeds native OpenSearch anomaly detectors.

## Prerequisites

- Docker Desktop using Linux containers, with at least 8 GiB available to Docker.
- Docker Compose v2.
- Python 3.12 through `uv`.
- Node.js 24 LTS and npm for host-side frontend checks.
- On Linux/WSL, OpenSearch requires `vm.max_map_count=262144`. Check it before startup; do not change host settings without understanding the impact.

## Local setup

1. Generate ignored local credentials:

   `uv run --project backend python scripts/generate_local_secrets.py`

2. Validate and build:

   `docker compose -f docker-compose.yml -f docker-compose.dev.yml config --quiet`

   `docker compose -f docker-compose.yml -f docker-compose.dev.yml build api frontend compatibility-probe`

3. Start OpenSearch and bootstrap twice to verify idempotence:

   `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d opensearch`

   `docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile tools run --rm bootstrap`

4. Start the stack and run the compatibility probe:

   `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d`

   `docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile tools run --rm compatibility-probe`

Local endpoints are bound to loopback: API `http://127.0.0.1:8000`, frontend `http://127.0.0.1:4173`, and the development-only Dashboards inspection port `http://127.0.0.1:5601`. OpenSearch, OTLP, and Data Prepper ports are not published.

OpenSearch uses its demo TLS certificate only for this local phase. The API explicitly allows certificate verification to be disabled only when `AIOPS_ENVIRONMENT=development`. Deployment TLS is Phase 10.

Do not use `docker compose down -v` for ordinary work: it deletes the persistent OpenSearch and Collector queue volumes.

## Phase 2 demo traffic

Build and start the three private demo services:

`docker compose -f docker-compose.yml -f docker-compose.dev.yml build order-service payment-service inventory-service load-generator`

`docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d payment-service inventory-service order-service`

Run bounded normal traffic without leaving a background generator:

`docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile load run --rm -e LOAD_DURATION_SECONDS=10 -e LOAD_REQUESTS_PER_SECOND=2 load-generator`

Fault routes are absent by default. For local demo fault checks, set `FAULT_INJECTION_ENABLED=true`, recreate Payment and Inventory, then select one of `payment-latency`, `payment-errors`, or `inventory-errors` with `LOAD_SCENARIO`. Every fault request has a bounded duration and automatically ceases to affect requests at expiry. Do not enable faults in production.

Run focused Phase 2 tests:

`uv sync --project apps --frozen --all-extras`

`uv run --project apps ruff check apps`

`uv run --project apps pytest -c apps/pyproject.toml apps/tests`

## Phase 3 telemetry

The three services export OTLP/gRPC to the existing Collector at `otel-collector:4317`. Resource identity is configured with `OTEL_SERVICE_NAME`, `OTEL_SERVICE_NAMESPACE`, `SERVICE_VERSION`, and `DEPLOYMENT_ENVIRONMENT`. The native application metrics are:

- `demo.http.server.requests`: completed business-route requests, unit `{request}`.
- `demo.http.server.errors`: completed business-route requests with a 5xx response, unit `{request}`.
- `demo.http.server.duration`: business-route duration histogram, unit `ms`.

Health, documentation, and `/__faults` routes are excluded from these application metrics.

After generating a normal order, use the bounded read-only inspector to verify a connected trace, correlated logs, and persisted metrics. `PHASE3_TRACE_ID` is optional; when omitted, the inspector selects the newest real `demo-shop` Order trace:

`docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile tools run --rm --no-deps --entrypoint python compatibility-probe scripts/inspect_phase3.py`

The inspector prints only selected telemetry evidence and never prints OpenSearch credentials or request payloads.

## Phase 5 aggregation and detection

The persistent `aggregation-worker` reads only normalized completed spans through `TelemetryRepository`, waits 90 seconds after each minute, and writes deterministic service buckets. Detection requires at least 20 valid SERVER requests in a finalized minute. Empty and low-volume minutes are persisted as `insufficient`, never as healthy zeroes.

Phase 5 uses deterministic nearest-rank p95: sort eligible millisecond durations and select rank `ceil(0.95 * n)`. This is tested at zero, one, repeated, minimum-sample, and skewed inputs. The Phase 5 completion report records its difference from the Phase 0 TDigest wording.

Provision or reconcile the six native detectors after eligible buckets exist:

`docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile tools run --rm detector-provisioner`

Run the bounded inspector to show recent buckets, native detector states, and normalized native results:

`docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile tools run --rm phase5-inspector`

Focused host checks:

`uv run --project backend ruff check backend/app backend/tests scripts`

`uv run --project backend pytest backend/tests`

OpenSearch 3.8 limits detector names to 64 characters. The readable detector name therefore uses the registered service name; the registry key and exact detector filter retain the full deterministic service ID.
