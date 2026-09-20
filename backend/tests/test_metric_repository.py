from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.config import Settings
from app.models.telemetry import QueryMetadata, ServiceReference, TelemetryQueryResult
from app.opensearch.query import OpenSearchQueryFailure
from app.repositories.metrics import MetricBucketRepository
from app.repositories.telemetry import TelemetryRepositoryError
from app.telemetry.aggregation.service import aggregate_minute
from app.workers.aggregation import AggregationWorker

NOW = datetime(2026, 9, 19, 12, 3, tzinfo=UTC)
SERVICE = ServiceReference(
    namespace="demo-shop", environment="development", name="payment-service"
)


def settings() -> Settings:
    return Settings(
        opensearch_username="worker",
        opensearch_password="not-a-real-password",
    )


def empty_result():
    return TelemetryQueryResult(
        items=[],
        metadata=QueryMetadata(
            partial=False,
            truncated=False,
            reasons=[],
            returned_count=0,
            matched_count=0,
        ),
    )


def finalized_bucket():
    base = aggregate_minute(
        SERVICE,
        datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
        empty_result(),
        computed_at=NOW,
        finalized=True,
    )
    return base.model_copy(
        update={
            "request_count": 20,
            "source_count": 20,
            "error_count": 1,
            "error_rate": 0.05,
            "latency_mean_ms": 20.0,
            "latency_p95_ms": 30.0,
            "quality_status": "complete",
            "quality_reasons": [],
            "eligible_for_detection": True,
        }
    )


class MemoryClient:
    def __init__(self):
        self.documents: dict[tuple[str, str], dict[str, Any]] = {}
        self.puts = 0
        self.failure: OpenSearchQueryFailure | None = None

    async def get_document(self, index, document_id):
        if self.failure:
            raise self.failure
        value = self.documents.get((index, document_id))
        if value is None:
            return None
        return {"_source": value, "_seq_no": 1, "_primary_term": 1}

    async def put_document(self, index, document_id, document, **kwargs):
        if self.failure:
            raise self.failure
        self.puts += 1
        self.documents[(index, document_id)] = dict(document)
        return {"result": "created"}


@pytest.mark.asyncio
async def test_finalized_replay_is_one_logical_document_and_late_values_freeze():
    client = MemoryClient()
    repository = MetricBucketRepository(client, settings())
    original = finalized_bucket()
    assert await repository.save_finalized(original) == original
    replay = original.model_copy(
        update={
            "computed_at": "2026-09-19T12:03:10Z",
            "finalized_at": "2026-09-19T12:03:10Z",
            "source_visible_through": "2026-09-19T12:03:10Z",
        }
    )
    assert await repository.save_finalized(replay) == original
    assert client.puts == 1

    late = original.model_copy(
        update={
            "request_count": 21,
            "source_count": 21,
            "error_count": 2,
            "error_rate": 2 / 21,
            "latency_mean_ms": 99.0,
            "latency_p95_ms": 999.0,
            "computed_at": "2026-09-19T12:04:00Z",
            "source_visible_through": "2026-09-19T12:04:00Z",
        }
    )
    saved = await repository.save_finalized(late)
    assert saved.request_count == 20
    assert saved.error_rate == 0.05
    assert saved.latency_p95_ms == 30
    assert saved.late_span_count == 1
    assert saved.quality_status == "partial"
    assert saved.eligible_for_detection is True
    assert client.puts == 2


@pytest.mark.asyncio
async def test_unavailable_opensearch_is_explicit_and_retryable():
    client = MemoryClient()
    client.failure = OpenSearchQueryFailure("unavailable")
    repository = MetricBucketRepository(client, settings())
    with pytest.raises(TelemetryRepositoryError) as caught:
        await repository.save_finalized(finalized_bucket())
    assert caught.value.code == "unavailable"
    assert caught.value.retryable is True


class EmptyTelemetry:
    async def search_spans(self, service, start, end, *, kind, limit):
        assert kind == "SERVER"
        return empty_result()


class CapturingBuckets:
    def __init__(self):
        self.buckets = []
        self.states = []

    async def get_worker_state(self, worker_id):
        return None

    async def save_finalized(self, bucket):
        self.buckets.append(bucket)
        return bucket

    async def save_worker_state(self, state, *, concurrency):
        self.states.append((state, concurrency))


@pytest.mark.asyncio
async def test_worker_persists_progress_only_after_bucket_publication():
    buckets = CapturingBuckets()
    worker = AggregationWorker(EmptyTelemetry(), buckets, settings())
    processed = await worker.run_once(NOW)
    assert processed == 3
    assert len(buckets.buckets) == 3
    assert len(buckets.states) == 3
    boundary = NOW - timedelta(seconds=90)
    expected = boundary.replace(second=0, microsecond=0).isoformat().replace("+00:00", "Z")
    assert all(item[0].cursor.finalized_through == expected for item in buckets.states)
