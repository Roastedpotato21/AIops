from functools import lru_cache

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OrderSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    payment_service_url: AnyHttpUrl = "http://payment-service:8000"
    inventory_service_url: AnyHttpUrl = "http://inventory-service:8000"
    http_timeout_seconds: float = Field(default=2.0, gt=0, le=30)

    def payment_endpoint(self) -> str:
        return f"{str(self.payment_service_url).rstrip('/')}/payments"

    def inventory_endpoint(self) -> str:
        return f"{str(self.inventory_service_url).rstrip('/')}/reserve"


@lru_cache
def get_settings() -> OrderSettings:
    return OrderSettings()
