import asyncio
import logging

from app.config import get_settings
from app.incidents.engine import IncidentEngine, IneligibleAnomaly
from app.incidents.evidence import TelemetryEvidenceCollector
from app.opensearch.query import OpenSearchQueryClient
from app.repositories.incidents import OpenSearchIncidentRepository
from app.repositories.telemetry import TelemetryRepository

LOGGER = logging.getLogger("aiops.incident-worker")


async def run_once(
    engine: IncidentEngine,
    repository: OpenSearchIncidentRepository,
    *,
    owner_id: str,
) -> int:
    processed = 0
    for anomaly in await repository.pending_anomalies():
        try:
            await engine.process(anomaly)
        except IneligibleAnomaly:
            pass
        await repository.save_worker_progress(anomaly, owner_id=owner_id)
        processed += 1
    return processed


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = get_settings()
    client = OpenSearchQueryClient(settings)
    repository = OpenSearchIncidentRepository(client, settings)
    telemetry = TelemetryRepository(client, settings)
    engine = IncidentEngine(
        repository,
        evidence_provider=TelemetryEvidenceCollector(
            telemetry, trace_alias=settings.spans_read_alias
        ),
        allow_development_fixtures=(
            settings.environment == "development" and settings.allow_development_fixtures
        ),
    )
    try:
        while True:
            count = await run_once(engine, repository, owner_id=settings.incident_worker_owner_id)
            if count:
                LOGGER.info("processed normalized anomaly records count=%d", count)
            await asyncio.sleep(settings.incident_poll_seconds)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
