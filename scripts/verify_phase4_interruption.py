import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.models.telemetry import ServiceReference, utc_timestamp_to_ns
from app.opensearch.query import OpenSearchQueryClient
from app.repositories.telemetry import TelemetryRepository

DEADLINE_SECONDS = min(int(os.environ.get("PHASE4_DEADLINE_SECONDS", "60")), 120)
ARTIFACT = Path(
    os.environ.get(
        "PHASE4_INTERRUPTION_ARTIFACT_PATH",
        "/artifacts/phase4-interruption.json",
    )
)


def parse_utc(name: str) -> datetime:
    return datetime.fromisoformat(os.environ[name].replace("Z", "+00:00")).astimezone(UTC)


async def run() -> dict[str, object]:
    start = parse_utc("PHASE4_INTERRUPTION_START")
    recovered = parse_utc("PHASE4_COLLECTOR_RECOVERED")
    settings = Settings(
        opensearch_url=os.environ.get("OPENSEARCH_URL", "https://opensearch:9200"),
        opensearch_username=os.environ["OPENSEARCH_ADMIN_USERNAME"],
        opensearch_password=os.environ["OPENSEARCH_ADMIN_PASSWORD"],
        opensearch_verify_tls=False,
    )
    client = OpenSearchQueryClient(settings)
    repository = TelemetryRepository(client, settings)
    service = ServiceReference(
        namespace="demo-shop",
        environment="development",
        name="order-service",
    )
    deadline = time.monotonic() + DEADLINE_SECONDS
    try:
        while True:
            now = datetime.now(UTC)
            spans = await repository.search_spans(service, start, now, limit=100)
            roots = [
                span
                for span in spans.items
                if span.kind == "SERVER"
                and span.name == "POST /orders"
                and span.http_status_code == 200
            ]
            outage = [
                span
                for span in roots
                if utc_timestamp_to_ns(span.end_time)
                <= int(recovered.timestamp() * 1_000_000_000)
            ]
            recovery = [
                span
                for span in roots
                if utc_timestamp_to_ns(span.end_time)
                > int(recovered.timestamp() * 1_000_000_000)
            ]
            if recovery and (outage or time.monotonic() >= deadline):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("No post-recovery telemetry became queryable")
            await asyncio.sleep(1)

        duplicate_count = spans.metadata.duplicate_count
        conflict_count = spans.metadata.duplicate_conflict_count
        for trace_id in {span.trace_id for span in outage + recovery}:
            trace = await repository.get_trace(
                trace_id,
                start_time=start,
                end_time=now,
            )
            duplicate_count += trace.metadata.duplicate_count
            conflict_count += trace.metadata.duplicate_conflict_count
        result: dict[str, object] = {
            "application_requests_succeeded": 2,
            "outage_trace_ids": sorted({span.trace_id for span in outage}),
            "recovery_trace_ids": sorted({span.trace_id for span in recovery}),
            "outage_telemetry_recovered": bool(outage),
            "post_recovery_telemetry_queryable": bool(recovery),
            "logical_duplicate_count": duplicate_count,
            "duplicate_conflict_count": conflict_count,
            "partial": spans.metadata.partial,
        }
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        await client.close()


def main() -> int:
    result = asyncio.run(run())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
