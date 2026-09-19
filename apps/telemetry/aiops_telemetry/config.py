import os
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TelemetrySettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    telemetry_enabled: bool = False
    otel_service_name: str = Field(min_length=1, max_length=63)
    otel_service_namespace: str = Field(default="demo-shop", min_length=1, max_length=63)
    service_version: str = Field(default="0.3.0", min_length=1, max_length=128)
    deployment_environment: str = Field(default="development", min_length=1, max_length=63)
    service_instance_id: str | None = Field(default=None, max_length=128)
    otel_exporter_otlp_endpoint: str = "http://otel-collector:4317"
    otel_exporter_otlp_insecure: bool = True
    otel_batch_max_queue_size: int = Field(default=2_048, ge=128, le=8_192)
    otel_batch_max_export_batch_size: int = Field(default=512, ge=1, le=2_048)
    otel_batch_schedule_delay_millis: int = Field(default=1_000, ge=100, le=10_000)
    otel_metric_export_interval_millis: int = Field(default=5_000, ge=1_000, le=60_000)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator(
        "otel_service_name", "otel_service_namespace", "deployment_environment"
    )
    @classmethod
    def validate_label(cls, value: str) -> str:
        if not value.replace("-", "").replace("_", "").replace(".", "").isalnum():
            raise ValueError("must contain only letters, digits, dots, underscores, or hyphens")
        return value


def load_telemetry_settings(default_service_name: str) -> TelemetrySettings:
    return TelemetrySettings(
        otel_service_name=os.environ.get("OTEL_SERVICE_NAME", default_service_name)
    )
