import asyncio
import time
from collections.abc import Callable


class FaultController:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = asyncio.Lock()
        self._expires_at: float | None = None

    async def arm(self, duration_seconds: float) -> None:
        async with self._lock:
            self._expires_at = self._clock() + duration_seconds

    async def should_error(self) -> bool:
        async with self._lock:
            if self._expires_at is None:
                return False
            if self._clock() >= self._expires_at:
                self._expires_at = None
                return False
            return True
