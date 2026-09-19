from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
    service: Literal["inventory-service"] = "inventory-service"


class InventoryRequest(StrictModel):
    product_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    quantity: Annotated[StrictInt, Field(gt=0, le=1_000)]


class InventoryResponse(StrictModel):
    status: Literal["reserved"] = "reserved"
    reservation_id: str


class FaultRequest(StrictModel):
    mode: Literal["errors"]
    duration_seconds: float = Field(gt=0, le=300, allow_inf_nan=False)


class FaultResponse(StrictModel):
    status: Literal["armed"] = "armed"
    expires_in_seconds: float
