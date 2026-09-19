import httpx
import pytest
from payment_service.config import PaymentSettings
from payment_service.faults import FaultController
from payment_service.main import create_app


@pytest.mark.asyncio
async def test_payment_normal_success() -> None:
    app = create_app(PaymentSettings(app_environment="test"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://payment"
    ) as client:
        response = await client.post("/payments", json={"amount": 100.0})
    assert response.status_code == 200
    assert response.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_payment_latency_fault_works_and_expires() -> None:
    now = [10.0]
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    faults = FaultController(clock=lambda: now[0], sleeper=fake_sleep)
    settings = PaymentSettings(
        app_environment="test",
        fault_injection_enabled=True,
        fault_max_duration_seconds=5,
    )
    app = create_app(settings, faults)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://payment"
    ) as client:
        armed = await client.post(
            "/__faults",
            json={"mode": "latency", "duration_seconds": 1.0, "latency_ms": 25},
        )
        delayed = await client.post("/payments", json={"amount": 100.0})
        now[0] = 11.1
        recovered = await client.post("/payments", json={"amount": 100.0})
    assert armed.status_code == 200
    assert delayed.status_code == 200
    assert recovered.status_code == 200
    assert delays == [0.025]


@pytest.mark.asyncio
async def test_payment_fault_route_is_unavailable_when_disabled() -> None:
    app = create_app(
        PaymentSettings(app_environment="development", fault_injection_enabled=False)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://payment"
    ) as client:
        response = await client.post(
            "/__faults",
            json={"mode": "errors", "duration_seconds": 1.0},
        )
    assert response.status_code == 404
