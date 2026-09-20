import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.config import Settings, get_settings
from app.models.detection import (
    AggregationCursor,
    AggregationWorkerState,
    deterministic_id,
)
from app.models.telemetry import ServiceReference
from app.opensearch.query import OpenSearchQueryClient
from app.repositories.metrics import MetricBucketRepository
from app.repositories.telemetry import TelemetryRepository
from app.telemetry.aggregation.service import aggregate_minute, service_key, utc

LOGGER = logging.getLogger("aiops.aggregation")
AGGREGATION_VERSION = "1.0.0"
REPLAY_OVERLAP = timedelta(minutes=10)
MAX_FORWARD_BATCH = timedelta(minutes=10)
SERVICES = (
    ServiceReference(
        namespace="demo-shop",
        environment="development",
        name="order-service",
    ),
    ServiceReference(
        namespace="demo-shop",
        environment="development",
        name="payment-service",
    ),
    ServiceReference(
        namespace="demo-shop",
        environment="development",
        name="inventory-service",
    ),
)


def finalizable_boundary(now: datetime, delay_seconds: int) -> datetime:
    delayed = now.astimezone(UTC) - timedelta(seconds=delay_seconds)
    return delayed.replace(second=0, microsecond=0)


def processing_range(
    finalized_through: datetime | None,
    boundary: datetime,
) -> tuple[datetime, datetime]:
    """Return a bounded, overlapping range without skipping outage gaps."""
    if finalized_through is None:
        return boundary - timedelta(minutes=1), boundary
    if finalized_through >= boundary:
        return boundary - REPLAY_OVERLAP, boundary
    start = finalized_through - REPLAY_OVERLAP
    end = min(boundary, finalized_through + MAX_FORWARD_BATCH)
    return start, end


class AggregationWorker:
    def __init__(
        self,
        telemetry: TelemetryRepository,
        buckets: MetricBucketRepository,
        settings: Settings,
    ) -> None:
        self._telemetry = telemetry
        self._buckets = buckets
        self._settings = settings

    async def run_service(self, service: ServiceReference, now: datetime) -> int:
        key = service_key(service)
        worker_id = deterministic_id("worker", ["aggregation", key.service_id])
        current = await self._buckets.get_worker_state(worker_id)
        boundary = finalizable_boundary(
            now,
            self._settings.aggregation_completeness_delay_seconds,
        )
        if current is None:
            start, processing_end = processing_range(None, boundary)
            concurrency = None
        else:
            stored, sequence, primary_term = current
            finalized_through = datetime.fromisoformat(
                stored.cursor.finalized_through.replace("Z", "+00:00")
            )
            start, processing_end = processing_range(finalized_through, boundary)
            concurrency = (sequence, primary_term)
        processed = 0
        cursor = start
        while cursor < processing_end:
            end = cursor + timedelta(minutes=1)
            spans = await self._telemetry.search_spans(
                service,
                cursor,
                end,
                kind="SERVER",
                limit=200,
            )
            bucket = aggregate_minute(
                service,
                cursor,
                spans,
                computed_at=now,
                finalized=True,
                aggregation_version=AGGREGATION_VERSION,
                minimum_samples=self._settings.aggregation_minimum_samples,
                sampling_fraction=self._settings.telemetry_sampling_fraction,
            )
            await self._buckets.save_finalized(bucket)
            cursor = end
            processed += 1
        timestamp = utc(now)
        state = AggregationWorkerState(
            schema_version="1.0.0",
            record_kind="worker_cursor",
            worker_state_id=worker_id,
            role="aggregation",
            partition=key.service_id,
            cursor=AggregationCursor(
                kind="aggregation",
                service_id=key.service_id,
                finalized_through=utc(processing_end),
                aggregation_version=AGGREGATION_VERSION,
            ),
            owner_id=self._settings.worker_owner_id,
            heartbeat_at=timestamp,
            status="running",
            last_error=None,
            updated_at=timestamp,
        )
        await self._buckets.save_worker_state(state, concurrency=concurrency)
        return processed

    async def run_once(self, now: datetime | None = None) -> int:
        observed = now or datetime.now(UTC)
        return sum(
            [await self.run_service(service, observed) for service in SERVICES]
        )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    client = OpenSearchQueryClient(settings)
    worker = AggregationWorker(
        TelemetryRepository(client, settings),
        MetricBucketRepository(client, settings),
        settings,
    )
    try:
        while True:
            try:
                processed = await worker.run_once()
                LOGGER.info("aggregation pass completed windows=%s", processed)
            except Exception:
                LOGGER.exception("aggregation pass failed")
            await asyncio.sleep(settings.aggregation_poll_seconds)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
