import httpx
import pytest
from inventory_service.config import InventorySettings
from inventory_service.faults import FaultController
from inventory_service.main import create_app


@pytest.mark.asyncio
async def test_inventory_normal_success() -> None:
    app = create_app(InventorySettings(app_environment="test"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inventory"
    ) as client:
        response = await client.post(
            "/reserve", json={"product_id": "demo-product-1", "quantity": 1}
        )
    assert response.status_code == 200
    assert response.json()["status"] == "reserved"


@pytest.mark.asyncio
async def test_inventory_error_fault_expires() -> None:
    now = [20.0]
    faults = FaultController(clock=lambda: now[0])
    settings = InventorySettings(
        app_environment="test",
        fault_injection_enabled=True,
        fault_max_duration_seconds=5,
    )
    app = create_app(settings, faults)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inventory"
    ) as client:
        armed = await client.post(
            "/__faults", json={"mode": "errors", "duration_seconds": 1.0}
        )
        failed = await client.post(
            "/reserve", json={"product_id": "demo-product-1", "quantity": 1}
        )
        now[0] = 21.1
        recovered = await client.post(
            "/reserve", json={"product_id": "demo-product-1", "quantity": 1}
        )
    assert armed.status_code == 200
    assert failed.status_code == 500
    assert recovered.status_code == 200


@pytest.mark.asyncio
async def test_inventory_fault_route_is_unavailable_when_disabled() -> None:
    app = create_app(
        InventorySettings(app_environment="development", fault_injection_enabled=False)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://inventory"
    ) as client:
        response = await client.post(
            "/__faults", json={"mode": "errors", "duration_seconds": 1.0}
        )
    assert response.status_code == 404
