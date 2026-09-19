from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
    service: Literal["order-service"] = "order-service"


class OrderRequest(StrictModel):
    product_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    quantity: Annotated[StrictInt, Field(gt=0, le=1_000)]
    amount: Annotated[StrictFloat, Field(gt=0, allow_inf_nan=False)]


class OrderResponse(StrictModel):
    status: Literal["completed"] = "completed"
    order_id: str
    payment_id: str
    reservation_id: str


class PaymentResponse(StrictModel):
    status: Literal["approved"]
    payment_id: str


class InventoryResponse(StrictModel):
    status: Literal["reserved"]
    reservation_id: str
