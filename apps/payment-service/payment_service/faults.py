import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

PaymentFaultMode = Literal["latency", "errors"]


@dataclass(frozen=True)
class ActiveFault:
    mode: PaymentFaultMode
    expires_at: float
    latency_seconds: float


class FaultController:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._clock = clock
        self._sleeper = sleeper
        self._lock = asyncio.Lock()
        self._active: ActiveFault | None = None

    async def arm(
        self, mode: PaymentFaultMode, duration_seconds: float, latency_ms: int
    ) -> None:
        async with self._lock:
            self._active = ActiveFault(
                mode=mode,
                expires_at=self._clock() + duration_seconds,
                latency_seconds=latency_ms / 1000,
            )

    async def apply(self) -> PaymentFaultMode | None:
        async with self._lock:
            active = self._active
            if active is None:
                return None
            if self._clock() >= active.expires_at:
                self._active = None
                return None
        if active.mode == "latency":
            await self._sleeper(active.latency_seconds)
        return active.mode
