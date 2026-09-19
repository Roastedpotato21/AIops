import re
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import ValidationError

from order_service.config import OrderSettings, get_settings
from order_service.models import (
    HealthResponse,
    InventoryResponse,
    OrderRequest,
    OrderResponse,
    PaymentResponse,
)

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _request_id(value: str | None) -> str:
    if value is None:
        return str(uuid4())
    if not REQUEST_ID_PATTERN.fullmatch(value):
        raise HTTPException(status_code=400, detail="Invalid X-Request-ID")
    return value


def _downstream_failure(code: str, message: str, status_code: int = 502) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def create_app(
    settings: OrderSettings | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    resolved = settings or get_settings()
    application = FastAPI(title="AIOps Demo Order Service", version="0.2.0")

    @application.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    async def submit_order(
        request: OrderRequest, client: httpx.AsyncClient, request_id: str
    ) -> OrderResponse:
        headers = {"X-Request-ID": request_id}
        try:
            payment_http = await client.post(
                resolved.payment_endpoint(),
                json={"amount": request.amount},
                headers=headers,
                timeout=resolved.http_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise _downstream_failure(
                "payment_timeout", "Payment service timed out", status_code=504
            ) from exc
        except httpx.RequestError as exc:
            raise _downstream_failure("payment_unavailable", "Payment service unavailable") from exc
        if not payment_http.is_success:
            raise _downstream_failure("payment_failed", "Payment service rejected the order")
        try:
            payment = PaymentResponse.model_validate(payment_http.json())
        except (ValueError, ValidationError) as exc:
            raise _downstream_failure(
                "payment_invalid_response", "Payment response was invalid"
            ) from exc

        try:
            inventory_http = await client.post(
                resolved.inventory_endpoint(),
                json={"product_id": request.product_id, "quantity": request.quantity},
                headers=headers,
                timeout=resolved.http_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise _downstream_failure(
                "inventory_timeout", "Inventory service timed out", status_code=504
            ) from exc
        except httpx.RequestError as exc:
            raise _downstream_failure(
                "inventory_unavailable", "Inventory service unavailable"
            ) from exc
        if not inventory_http.is_success:
            raise _downstream_failure(
                "inventory_failed", "Inventory service could not reserve the order"
            )
        try:
            inventory = InventoryResponse.model_validate(inventory_http.json())
        except (ValueError, ValidationError) as exc:
            raise _downstream_failure(
                "inventory_invalid_response", "Inventory response was invalid"
            ) from exc

        return OrderResponse(
            order_id=str(uuid4()),
            payment_id=payment.payment_id,
            reservation_id=inventory.reservation_id,
        )

    @application.post("/orders", response_model=OrderResponse)
    async def create_order(
        request: OrderRequest,
        response: Response,
        x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
    ) -> OrderResponse:
        request_id = _request_id(x_request_id)
        response.headers["X-Request-ID"] = request_id
        if http_client is not None:
            return await submit_order(request, http_client, request_id)
        async with httpx.AsyncClient() as client:
            return await submit_order(request, client, request_id)

    return application


app = create_app()
