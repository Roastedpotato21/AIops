import asyncio
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict

from load_generator.config import LoadSettings


class LoadSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_requests: int
    success_count: int
    error_count: int
    elapsed_seconds: float
    average_latency_ms: float


async def configure_scenario(settings: LoadSettings, client: httpx.AsyncClient) -> None:
    if settings.load_scenario == "normal":
        return
    if settings.load_scenario == "inventory-errors":
        endpoint = settings.inventory_fault_endpoint()
        payload: dict[str, object] = {
            "mode": "errors",
            "duration_seconds": settings.fault_duration_seconds,
        }
    else:
        endpoint = settings.payment_fault_endpoint()
        payload = {
            "mode": "latency" if settings.load_scenario == "payment-latency" else "errors",
            "duration_seconds": settings.fault_duration_seconds,
            "latency_ms": settings.fault_latency_ms,
        }
    response = await client.post(
        endpoint,
        json=payload,
        timeout=settings.load_http_timeout_seconds,
    )
    if not response.is_success:
        raise RuntimeError("Fault scenario could not be enabled; verify the development gate")


async def run_load(
    settings: LoadSettings,
    *,
    http_client: httpx.AsyncClient | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> LoadSummary:
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient()
    started = clock()
    deadline = started + settings.load_duration_seconds
    interval = 1 / settings.load_requests_per_second
    next_request_at = started
    success_count = 0
    error_count = 0
    latency_total = 0.0
    try:
        await configure_scenario(settings, client)
        while next_request_at < deadline:
            await sleeper(max(0.0, next_request_at - clock()))
            if clock() >= deadline:
                break
            request_started = clock()
            try:
                response = await client.post(
                    settings.order_endpoint(),
                    json={"product_id": "demo-product-1", "quantity": 1, "amount": 100.0},
                    headers={"X-Request-ID": str(uuid4())},
                    timeout=settings.load_http_timeout_seconds,
                )
                if response.is_success:
                    success_count += 1
                else:
                    error_count += 1
            except httpx.RequestError:
                error_count += 1
            latency_total += max(0.0, clock() - request_started)
            next_request_at = max(next_request_at + interval, clock())
    finally:
        if owns_client:
            await client.aclose()
    total = success_count + error_count
    elapsed = max(0.0, clock() - started)
    return LoadSummary(
        total_requests=total,
        success_count=success_count,
        error_count=error_count,
        elapsed_seconds=round(elapsed, 3),
        average_latency_ms=round((latency_total / total) * 1_000, 3) if total else 0.0,
    )
