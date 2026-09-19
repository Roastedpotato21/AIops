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
