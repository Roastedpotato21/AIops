# AIOps platform

Phase 1 establishes the repository, a FastAPI health/readiness shell, a React/Vite status shell, and a local OpenTelemetry → Data Prepper → OpenSearch compatibility stack. Product services, detectors, incidents, agents, and dashboard features are deliberately absent.

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
