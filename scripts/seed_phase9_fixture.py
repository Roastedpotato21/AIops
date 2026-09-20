"""Seed one idempotent, visibly labeled Phase 9 development anomaly fixture."""

import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Any

import httpx
from app.incidents.development_fixture import FIXTURE_SOURCE_INDEX, build_fixture
from app.models.detection import ServiceMetricBucket

TARGET_INDEX = "aiops-anomalies-v1"


async def _request(
    client: httpx.AsyncClient, method: str, path: str, *, json_body: dict[str, Any]
) -> dict[str, Any]:
    response = await client.request(method, path, json=json_body)
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Phase 9 fixture operation failed ({response.status_code})")
    return response.json()


async def main() -> None:
    if os.environ.get("ALLOW_DEVELOPMENT_FIXTURES", "false").lower() != "true":
        raise RuntimeError("development fixtures are disabled")
    base_url = os.environ.get("OPENSEARCH_URL", "https://opensearch:9200")
    auth = (
        os.environ["OPENSEARCH_ADMIN_USERNAME"],
        os.environ["OPENSEARCH_ADMIN_PASSWORD"],
    )
    query = {
        "size": 50,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"service.name": "payment-service"}},
                    {"term": {"quality_status": "complete"}},
                    {"term": {"eligible_for_detection": True}},
                    {"term": {"late_span_count": 0}},
                ]
            }
        },
        "sort": [{"window.start": "desc"}, {"bucket_id": "asc"}],
    }
    async with httpx.AsyncClient(
        base_url=base_url,
        auth=auth,
        verify=False,
        timeout=10,
    ) as client:
        payload = await _request(
            client,
            "POST",
            "/aiops-service-metrics-v1/_search",
            json_body=query,
        )
        buckets = [
            ServiceMetricBucket.model_validate(hit["_source"])
            for hit in payload.get("hits", {}).get("hits", [])
        ]
        if len(buckets) < 11:
            raise RuntimeError("at least 11 detector-ready payment buckets are required")
        fixture = build_fixture(buckets[0], observed_at=datetime.now(UTC))
        await _request(
            client,
            "PUT",
            f"/{TARGET_INDEX}/_doc/{fixture.anomaly_id}?refresh=wait_for",
            json_body=fixture.model_dump(mode="json"),
        )
    print(
        json.dumps(
            {
                "anomaly_id": fixture.anomaly_id,
                "bucket_id": fixture.input_bucket_id,
                "fixture_source": True,
                "source_index": FIXTURE_SOURCE_INDEX,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
