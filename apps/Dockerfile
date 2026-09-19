FROM ghcr.io/astral-sh/uv:0.11.18@sha256:78bc42400d77b0678ba95765305c826652ed5431f399257271dda681d0318f03 AS uv
FROM python:3.12.12-slim@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c

WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY apps/pyproject.toml apps/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY apps/order-service/order_service /app/order-service/order_service
COPY apps/payment-service/payment_service /app/payment-service/payment_service
COPY apps/inventory-service/inventory_service /app/inventory-service/inventory_service
COPY apps/load-generator/load_generator /app/load-generator/load_generator
COPY apps/telemetry/aiops_telemetry /app/telemetry/aiops_telemetry

RUN useradd --create-home --uid 10001 demo
USER 10001:10001

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/telemetry:/app/order-service:/app/payment-service:/app/inventory-service:/app/load-generator" \
    PYTHONUNBUFFERED=1
