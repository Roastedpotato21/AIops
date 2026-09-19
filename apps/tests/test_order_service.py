from collections.abc import Awaitable, Callable

import httpx
import pytest
from order_service.config import OrderSettings
from order_service.main import create_app

ORDER = {"product_id": "demo-product-1", "quantity": 1, "amount": 100.0}


async def call_order(
    handler: Callable[[httpx.Request], Awaitable[httpx.Response]],
) -> tuple[httpx.Response, list[httpx.Request]]:
    downstream_requests: list[httpx.Request] = []

    async def recording_handler(request: httpx.Request) -> httpx.Response:
        downstream_requests.append(request)
        return await handler(request)

    downstream = httpx.AsyncClient(transport=httpx.MockTransport(recording_handler))
    app = create_app(
        OrderSettings(
            payment_service_url="http://payment-service:8000",
            inventory_service_url="http://inventory-service:8000",
            http_timeout_seconds=0.2,
        ),
        downstream,
    )
    async with downstream, httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://order"
    ) as client:
        response = await client.post(
            "/orders", json=ORDER, headers={"X-Request-ID": "request-123"}
        )
    return response, downstream_requests


@pytest.mark.asyncio
async def test_order_full_success_path() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/payments":
            return httpx.Response(200, json={"status": "approved", "payment_id": "pay-1"})
        return httpx.Response(
            200, json={"status": "reserved", "reservation_id": "reservation-1"}
        )

    response, requests = await call_order(handler)
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert [request.url.path for request in requests] == ["/payments", "/reserve"]
    assert all(request.headers["X-Request-ID"] == "request-123" for request in requests)
    assert response.headers["X-Request-ID"] == "request-123"


@pytest.mark.asyncio
async def test_payment_failure_propagates_without_inventory_call() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "Payment unavailable"})

    response, requests = await call_order(handler)
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "payment_failed"
    assert [request.url.path for request in requests] == ["/payments"]


@pytest.mark.asyncio
async def test_inventory_failure_propagates() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/payments":
            return httpx.Response(200, json={"status": "approved", "payment_id": "pay-1"})
        return httpx.Response(500, json={"detail": "Inventory unavailable"})

    response, requests = await call_order(handler)
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "inventory_failed"
    assert [request.url.path for request in requests] == ["/payments", "/reserve"]


@pytest.mark.asyncio
async def test_downstream_timeout_is_bounded() -> None:
    observed_timeout: dict[str, float] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        observed_timeout.update(request.extensions["timeout"])
        raise httpx.ReadTimeout("bounded timeout", request=request)

    response, requests = await call_order(handler)
    assert response.status_code == 504
    assert response.json()["detail"]["code"] == "payment_timeout"
    assert len(requests) == 1
    assert all(value == 0.2 for value in observed_timeout.values())
