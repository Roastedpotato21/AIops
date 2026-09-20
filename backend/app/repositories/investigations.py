from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.config import Settings
from app.models.investigation import InvestigationJob, InvestigationOutcome
from app.opensearch.query import OpenSearchQueryClient, OpenSearchQueryFailure
from app.repositories.telemetry import TelemetryRepositoryError


class InvestigationRepository:
    def __init__(self, client: OpenSearchQueryClient, settings: Settings) -> None:
        self._client = client
        self._index = settings.investigations_alias

    async def get_job(self, investigation_id: str) -> tuple[InvestigationJob, int, int] | None:
        try:
            document = await self._client.get_document(self._index, investigation_id)
            if document is None:
                return None
            return (
                InvestigationJob.model_validate(document["_source"]),
                int(document["_seq_no"]),
                int(document["_primary_term"]),
            )
        except (OpenSearchQueryFailure, KeyError, TypeError, ValueError, ValidationError) as exc:
            raise TelemetryRepositoryError("unavailable", retryable=True) from exc

    async def create_job(self, job: InvestigationJob) -> InvestigationJob:
        existing = await self.get_job(job.investigation_id)
        if existing is not None:
            return existing[0]
        try:
            await self._client.put_document(
                self._index,
                job.investigation_id,
                job.model_dump(mode="json"),
                refresh=True,
                create_only=True,
            )
            return job
        except OpenSearchQueryFailure as exc:
            if exc.code == "invalid_query":
                raced = await self.get_job(job.investigation_id)
                if raced is not None:
                    return raced[0]
            raise TelemetryRepositoryError("unavailable", retryable=True) from exc

    async def active_job(self, incident_id: str) -> InvestigationJob | None:
        hits = await self._search(
            {
                "size": 1,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"incident_id": incident_id}},
                            {"terms": {"state": ["queued", "running"]}},
                        ]
                    }
                },
                "sort": [{"created_at": "asc"}, {"investigation_id": "asc"}],
            }
        )
        return self._models(hits)[0] if hits else None

    async def claim_next(
        self, *, owner: str, now: datetime, lease_seconds: int = 30
    ) -> InvestigationJob | None:
        now_text = _utc(now)
        hits = await self._search(
            {
                "size": 10,
                "query": {
                    "bool": {
                        "should": [
                            {
                                "bool": {
                                    "filter": [{"term": {"state": "queued"}}],
                                    "should": [
                                        {
                                            "bool": {
                                                "must_not": {
                                                    "exists": {"field": "next_attempt_at"}
                                                }
                                            }
                                        },
                                        {"range": {"next_attempt_at": {"lte": now_text}}},
                                    ],
                                    "minimum_should_match": 1,
                                }
                            },
                            {
                                "bool": {
                                    "filter": [
                                        {"term": {"state": "running"}},
                                        {"range": {"lease_expires_at": {"lte": now_text}}},
                                    ]
                                }
                            },
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "sort": [{"created_at": "asc"}, {"investigation_id": "asc"}],
            }
        )
        for hit in hits:
            try:
                job = InvestigationJob.model_validate(hit["_source"])
                seq_no = int(hit["_seq_no"])
                primary_term = int(hit["_primary_term"])
            except (KeyError, TypeError, ValueError, ValidationError):
                continue
            if job.attempt_count >= 3:
                continue
            claimed = job.model_copy(
                update={
                    "state": "running",
                    "attempt_count": job.attempt_count + 1,
                    "attempt_id": uuid4(),
                    "lease_owner": owner,
                    "lease_expires_at": _utc(now + timedelta(seconds=lease_seconds)),
                    "next_attempt_at": None,
                    "started_at": job.started_at or now_text,
                    "updated_at": now_text,
                }
            )
            try:
                await self._client.put_document(
                    self._index,
                    job.investigation_id,
                    claimed.model_dump(mode="json"),
                    refresh=True,
                    if_seq_no=seq_no,
                    if_primary_term=primary_term,
                )
                return claimed
            except OpenSearchQueryFailure as exc:
                if exc.code != "invalid_query":
                    raise TelemetryRepositoryError("unavailable", retryable=True) from exc
        return None

    async def finish(
        self,
        investigation_id: str,
        attempt_id: UUID,
        outcome: InvestigationOutcome,
        *,
        now: datetime,
    ) -> InvestigationJob:
        record = await self.get_job(investigation_id)
        if record is None:
            raise TelemetryRepositoryError("unavailable", retryable=False)
        job, seq_no, primary_term = record
        if job.state != "running" or job.attempt_id != attempt_id:
            raise TelemetryRepositoryError("unavailable", retryable=False)
        retryable = (
            outcome.failure is not None and outcome.failure.retryable and job.attempt_count < 3
        )
        state = "queued" if retryable else ("succeeded" if outcome.report else "failed")
        updated = job.model_copy(
            update={
                "state": state,
                "lease_owner": None,
                "lease_expires_at": None,
                "next_attempt_at": _utc(now + _retry_delay(job.attempt_count))
                if retryable
                else None,
                "finished_at": None if retryable else _utc(now),
                "updated_at": _utc(now),
                "tool_calls_used": len(outcome.executions),
                "tool_executions": [*job.tool_executions, *outcome.executions][-24:],
                "additional_evidence_ids": list(
                    dict.fromkeys(
                        [
                            *job.additional_evidence_ids,
                            *[
                                evidence_id
                                for execution in outcome.executions
                                for evidence_id in execution.evidence_ids
                            ],
                        ]
                    )
                )[:100],
                "input_tokens": outcome.usage.input_tokens,
                "output_tokens": outcome.usage.output_tokens,
                "cost_usd": outcome.usage.cost_usd,
                "last_error": outcome.failure,
                "report": outcome.report,
            }
        )
        try:
            await self._client.put_document(
                self._index,
                investigation_id,
                updated.model_dump(mode="json"),
                refresh=True,
                if_seq_no=seq_no,
                if_primary_term=primary_term,
            )
        except OpenSearchQueryFailure as exc:
            raise TelemetryRepositoryError("unavailable", retryable=True) from exc
        return updated

    async def _search(self, body: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        try:
            response = await self._client.search(self._index, body)
            hits = response["hits"]["hits"]
            if not isinstance(hits, list):
                raise TypeError
            return hits
        except (OpenSearchQueryFailure, KeyError, TypeError) as exc:
            raise TelemetryRepositoryError("unavailable", retryable=True) from exc

    @staticmethod
    def _models(hits: list[Mapping[str, Any]]) -> list[InvestigationJob]:
        try:
            return [InvestigationJob.model_validate(hit["_source"]) for hit in hits]
        except (KeyError, ValidationError) as exc:
            raise TelemetryRepositoryError("unavailable", retryable=False) from exc


def _retry_delay(attempt_count: int) -> timedelta:
    return timedelta(seconds=30 if attempt_count <= 1 else 120)


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
