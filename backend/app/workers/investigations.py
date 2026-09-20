import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.agent.backend import RepositoryToolBackend
from app.agent.investigator import Investigator
from app.agent.providers import OpenAIResponsesProvider, ReasoningProvider, UnavailableProvider
from app.agent.tools import ToolRegistry
from app.config import Settings, get_settings
from app.models.detection import Failure
from app.models.investigation import (
    InvestigationBudget,
    InvestigationOutcome,
    InvestigationRequest,
    ProviderUsage,
    ToolContext,
)
from app.opensearch.query import OpenSearchQueryClient
from app.repositories.incidents import OpenSearchIncidentRepository
from app.repositories.investigations import InvestigationRepository
from app.repositories.telemetry import TelemetryRepository, TelemetryRepositoryError

LOGGER = logging.getLogger("aiops.investigation-worker")


async def run_once(
    jobs: InvestigationRepository,
    incidents: OpenSearchIncidentRepository,
    backend: RepositoryToolBackend,
    provider: ReasoningProvider,
    settings: Settings,
    *,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
) -> int:
    started = now or datetime.now(UTC)
    current_time = clock or (lambda: datetime.now(UTC))
    job = await jobs.claim_next(owner=settings.investigation_worker_owner_id, now=started)
    if job is None:
        return 0
    assert job.attempt_id is not None
    try:
        incident = await incidents.get_incident(job.incident_id)
        bundle = await incidents.get_bundle(job.evidence_bundle_id)
        if incident is None or bundle is None or bundle.version != job.evidence_version:
            outcome = _failure("source_expired", "Pinned investigation evidence is unavailable")
        else:
            evidence = await incidents.get_evidence_items(bundle.evidence_ids)
            if len(evidence) != len(bundle.evidence_ids):
                outcome = _failure("source_expired", "Pinned evidence is incomplete")
            else:
                deadline = started + timedelta(seconds=settings.investigation_deadline_seconds)
                await backend.bind_incident(incident.incident_id)
                request = InvestigationRequest(
                    job_id=job.investigation_id,
                    incident=incident,
                    bundle=bundle,
                    initial_evidence=evidence,
                    context=ToolContext(
                        principal_id=job.requested_by,
                        job_id=job.investigation_id,
                        incident_id=incident.incident_id,
                        allowed_service_ids=[
                            item.service_id for item in incident.affected_services
                        ],
                        allowed_window=bundle.window,
                        deadline_at=_utc(deadline),
                        evidence_allowlist=bundle.evidence_ids,
                    ),
                    budget=InvestigationBudget(
                        max_tool_calls=settings.investigation_max_tool_calls,
                        max_duration_seconds=settings.investigation_deadline_seconds,
                    ),
                )
                outcome = await Investigator(model_id=job.model_id).investigate(
                    request,
                    ToolRegistry(backend, max_calls=settings.investigation_max_tool_calls),
                    provider,
                )
    except TelemetryRepositoryError as exc:
        outcome = _failure(exc.code, "Investigation dependency failed", exc.retryable)
    await jobs.finish(job.investigation_id, job.attempt_id, outcome, now=current_time())
    return 1


def provider_from_settings(settings: Settings) -> ReasoningProvider:
    if settings.llm_provider == "openai" and settings.llm_api_key is not None:
        return OpenAIResponsesProvider(settings.llm_api_key)
    return UnavailableProvider()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = get_settings()
    client = OpenSearchQueryClient(settings)
    incidents = OpenSearchIncidentRepository(client, settings)
    jobs = InvestigationRepository(client, settings)
    backend = RepositoryToolBackend(
        incidents, TelemetryRepository(client, settings), trace_alias=settings.spans_read_alias
    )
    provider = provider_from_settings(settings)
    try:
        while True:
            processed = await run_once(jobs, incidents, backend, provider, settings)
            if processed:
                LOGGER.info("processed investigation job count=%d", processed)
            await asyncio.sleep(settings.investigation_poll_seconds)
    finally:
        close = getattr(provider, "close", None)
        if close is not None:
            await close()
        await client.close()


def _failure(code: str, message: str, retryable: bool = False) -> InvestigationOutcome:
    return InvestigationOutcome(
        failure=Failure(code=code, message=message, retryable=retryable),
        executions=[],
        usage=ProviderUsage(),
    )


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    asyncio.run(main())
