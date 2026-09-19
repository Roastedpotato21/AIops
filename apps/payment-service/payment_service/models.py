from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
    service: Literal["payment-service"] = "payment-service"


class PaymentRequest(StrictModel):
    amount: Annotated[StrictFloat, Field(gt=0, allow_inf_nan=False)]


class PaymentResponse(StrictModel):
    status: Literal["approved"] = "approved"
    payment_id: str


class FaultRequest(StrictModel):
    mode: Literal["latency", "errors"]
    duration_seconds: float = Field(gt=0, le=300, allow_inf_nan=False)
    latency_ms: int = Field(default=250, ge=1, le=5_000, strict=True)


class FaultResponse(StrictModel):
    status: Literal["armed"] = "armed"
    expires_in_seconds: float
