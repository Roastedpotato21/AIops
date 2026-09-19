from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
    service: Literal["aiops-api"] = "aiops-api"
    version: str
    checked_at: datetime


class ReadinessCheck(StrictModel):
    name: Literal["configuration", "opensearch", "bootstrap"]
    state: Literal["pass", "fail"]
    reason_code: Literal[
        "missing_config", "unreachable", "unauthorized", "bootstrap_pending"
    ] | None
    checked_at: datetime


class ReadyResponse(StrictModel):
    status: Literal["ready", "not_ready"]
    checked_at: datetime
    checks: list[ReadinessCheck]
