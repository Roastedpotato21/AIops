from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from app.config import Settings
from app.models.detection import (
    AggregationWorkerState,
    ServiceMetricBucket,
)
from app.opensearch.query import OpenSearchQueryClient, OpenSearchQueryFailure
from app.repositories.telemetry import TelemetryRepositoryError


class MetricBucketRepository:
    def __init__(self, client: OpenSearchQueryClient, settings: Settings) -> None:
        self._client = client
        self._bucket_index = settings.service_metrics_alias
        self._state_index = settings.bootstrap_index

    async def get_bucket(self, bucket_id: str) -> ServiceMetricBucket | None:
        try:
            response = await self._client.get_document(self._bucket_index, bucket_id)
        except OpenSearchQueryFailure as exc:
            raise TelemetryRepositoryError(
                "unauthorized" if exc.code == "unauthorized" else "unavailable",
                retryable=exc.code == "unavailable",
            ) from None
        if response is None:
            return None
        try:
            return ServiceMetricBucket.model_validate(response["_source"])
        except (KeyError, TypeError, ValidationError) as exc:
            raise TelemetryRepositoryError("unavailable", retryable=False) from exc

    async def save_finalized(self, candidate: ServiceMetricBucket) -> ServiceMetricBucket:
        existing = await self.get_bucket(candidate.bucket_id)
        if existing is None:
            await self._put(self._bucket_index, candidate.bucket_id, candidate.model_dump())
            return candidate
        identity = ("bucket_id", "service", "window", "aggregation_version")
        if any(getattr(existing, field) != getattr(candidate, field) for field in identity):
            raise TelemetryRepositoryError("unavailable", retryable=False)
        immutable = (
            "request_count",
            "error_count",
            "error_rate",
            "latency_mean_ms",
            "latency_p95_ms",
            "source_count",
        )
        if candidate.source_count <= existing.source_count:
            if any(getattr(existing, field) != getattr(candidate, field) for field in immutable):
                raise TelemetryRepositoryError("unavailable", retryable=False)
            return existing
        late_count = max(
            existing.late_span_count,
            candidate.source_count - existing.source_count,
        )
        reasons = list(existing.quality_reasons)
        if "late_data" not in reasons:
            reasons.append("late_data")
        degraded = existing.model_copy(
            update={
                "late_span_count": late_count,
                "quality_status": "partial",
                "quality_reasons": reasons,
                "computed_at": candidate.computed_at,
                "source_visible_through": candidate.source_visible_through,
            }
        )
        await self._put(self._bucket_index, degraded.bucket_id, degraded.model_dump())
        return degraded

    async def get_worker_state(
        self,
        worker_state_id: str,
    ) -> tuple[AggregationWorkerState, int, int] | None:
        try:
            response = await self._client.get_document(self._state_index, worker_state_id)
        except OpenSearchQueryFailure as exc:
            raise TelemetryRepositoryError(
                "unauthorized" if exc.code == "unauthorized" else "unavailable",
                retryable=exc.code == "unavailable",
            ) from None
        if response is None:
            return None
        try:
            return (
                AggregationWorkerState.model_validate(response["_source"]),
                int(response["_seq_no"]),
                int(response["_primary_term"]),
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise TelemetryRepositoryError("unavailable", retryable=False) from exc

    async def save_worker_state(
        self,
        state: AggregationWorkerState,
        *,
        concurrency: tuple[int, int] | None,
    ) -> None:
        try:
            await self._client.put_document(
                self._state_index,
                state.worker_state_id,
                state.model_dump(),
                refresh=True,
                if_seq_no=concurrency[0] if concurrency else None,
                if_primary_term=concurrency[1] if concurrency else None,
            )
        except OpenSearchQueryFailure as exc:
            raise TelemetryRepositoryError(
                "unauthorized" if exc.code == "unauthorized" else "unavailable",
                retryable=exc.code == "unavailable",
            ) from None

    async def _put(
        self,
        index: str,
        document_id: str,
        document: Mapping[str, Any],
    ) -> None:
        try:
            await self._client.put_document(
                index,
                document_id,
                document,
                refresh=True,
            )
        except OpenSearchQueryFailure as exc:
            raise TelemetryRepositoryError(
                "unauthorized" if exc.code == "unauthorized" else "unavailable",
                retryable=exc.code == "unavailable",
            ) from None
