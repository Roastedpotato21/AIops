FROM python:3.12.12-slim@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.11.18@sha256:78bc42400d77b0678ba95765305c826652ed5431f399257271dda681d0318f03 /uv /uvx /bin/
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/app ./app
COPY scripts ./scripts
COPY tests/fixtures ./tests/fixtures
COPY infra/opensearch ./infra/opensearch

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
