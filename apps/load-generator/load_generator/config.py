from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LoadScenario = Literal["normal", "payment-latency", "payment-errors", "inventory-errors"]


class LoadSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    order_service_url: AnyHttpUrl = "http://order-service:8000"
    payment_service_url: AnyHttpUrl = "http://payment-service:8000"
    inventory_service_url: AnyHttpUrl = "http://inventory-service:8000"
    load_requests_per_second: float = Field(default=2.0, gt=0, le=100)
    load_duration_seconds: float = Field(default=30.0, gt=0, le=3_600)
    load_http_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    load_scenario: LoadScenario = "normal"
    fault_duration_seconds: float = Field(default=10.0, gt=0, le=300)
    fault_latency_ms: int = Field(default=750, ge=1, le=5_000)

    def order_endpoint(self) -> str:
        return f"{str(self.order_service_url).rstrip('/')}/orders"

    def payment_fault_endpoint(self) -> str:
        return f"{str(self.payment_service_url).rstrip('/')}/__faults"

    def inventory_fault_endpoint(self) -> str:
        return f"{str(self.inventory_service_url).rstrip('/')}/__faults"


@lru_cache
def get_settings() -> LoadSettings:
    return LoadSettings()
