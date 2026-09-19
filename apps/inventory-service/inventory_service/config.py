from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class InventorySettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_environment: Literal["development", "demo", "test", "production"] = "production"
    fault_injection_enabled: bool = False
    fault_max_duration_seconds: float = Field(default=60.0, gt=0, le=300)

    @property
    def faults_allowed(self) -> bool:
        return self.fault_injection_enabled and self.app_environment in {
            "development",
            "demo",
            "test",
        }


@lru_cache
def get_settings() -> InventorySettings:
    return InventorySettings()
