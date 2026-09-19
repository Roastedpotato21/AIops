import json

import httpx
import pytest
from load_generator.config import LoadSettings
from load_generator.runner import run_load


@pytest.mark.asyncio
async def test_load_generator_produces_expected_traffic() -> None:
    now = [0.0]
    order_requests: list[dict] = []

    async def fake_sleep(seconds: float) -> None:
        now[0] += seconds

    async def handler(request: httpx.Request) -> httpx.Response:
        order_requests.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "completed"})

    settings = LoadSettings(
        load_requests_per_second=10,
        load_duration_seconds=0.25,
        load_scenario="normal",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await run_load(
            settings,
            http_client=client,
            clock=lambda: now[0],
            sleeper=fake_sleep,
        )
    assert result.total_requests == 3
    assert result.success_count == 3
    assert result.error_count == 0
    assert len(order_requests) == 3
    assert all("scenario" not in request for request in order_requests)


@pytest.mark.asyncio
async def test_scenario_control_is_not_added_to_order_requests() -> None:
    now = [0.0]
    order_requests: list[dict] = []
    fault_requests: list[dict] = []

    async def fake_sleep(seconds: float) -> None:
        now[0] += seconds

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/__faults":
            fault_requests.append(body)
            return httpx.Response(200, json={"status": "armed", "expires_in_seconds": 1})
        order_requests.append(body)
        return httpx.Response(500, json={"detail": "Payment unavailable"})

    settings = LoadSettings(
        load_requests_per_second=10,
        load_duration_seconds=0.11,
        load_scenario="payment-errors",
        fault_duration_seconds=1,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await run_load(
            settings,
            http_client=client,
            clock=lambda: now[0],
            sleeper=fake_sleep,
        )
    assert fault_requests == [{"mode": "errors", "duration_seconds": 1.0, "latency_ms": 750}]
    assert result.error_count == 2
    assert all("scenario" not in request for request in order_requests)
