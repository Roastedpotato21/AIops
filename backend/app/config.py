from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AIOPS_", extra="forbid")

    environment: str = "development"
    build_version: str = "phase1-dev"
    opensearch_url: str = "https://opensearch:9200"
    opensearch_username: str = Field(min_length=1)
    opensearch_password: str = Field(min_length=12)
    opensearch_verify_tls: bool = False
    opensearch_ca_file: str | None = None
    bootstrap_index: str = "aiops-worker-state-v1"
    bootstrap_document_id: str = "platform-bootstrap-v1"
    logs_read_alias: str = "aiops-logs"
    spans_read_alias: str = "otel-v1-apm-span"
    metrics_read_alias: str = "aiops-metrics-raw"
    service_map_read_alias: str = "otel-v1-apm-service-map"
    service_metrics_alias: str = "aiops-service-metrics-v1"
    anomalies_alias: str = "aiops-anomalies-v1"
    detector_result_alias: str = "opensearch-ad-plugin-result-aiops-v1"
    opensearch_query_timeout_seconds: float = Field(default=5.0, gt=0, le=10)
    aggregation_completeness_delay_seconds: int = Field(default=90, ge=60, le=600)
    aggregation_poll_seconds: int = Field(default=10, ge=1, le=60)
    aggregation_minimum_samples: int = Field(default=20, ge=1, le=1_000)
    telemetry_sampling_fraction: float | None = Field(default=1.0, ge=0, le=1)
    worker_owner_id: str = Field(default="aggregation-worker-local", min_length=1, max_length=128)
    frontend_origin: str = "http://127.0.0.1:4173"

    @model_validator(mode="after")
    def enforce_tls_policy(self) -> "Settings":
        if not self.opensearch_verify_tls and self.environment != "development":
            raise ValueError("TLS verification may be disabled only in development")
        if self.opensearch_verify_tls and not self.opensearch_ca_file:
            raise ValueError("A CA file is required when TLS verification is enabled")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
