"""Verify intended reads and representative forbidden writes for worker identities."""

import asyncio
import json
import os

import httpx

BASE = os.environ.get("OPENSEARCH_URL", "https://opensearch:9200")

CHECKS = (
    (
        "aggregation",
        "OPENSEARCH_AGGREGATION_WORKER_USERNAME",
        "OPENSEARCH_AGGREGATION_WORKER_PASSWORD",
        "/aiops-service-metrics-v1/_search",
        "/aiops-incidents-v1/_doc/phase9-permission-probe",
    ),
    (
        "incident",
        "OPENSEARCH_INCIDENT_WORKER_USERNAME",
        "OPENSEARCH_INCIDENT_WORKER_PASSWORD",
        "/aiops-anomalies-v1/_search",
        "/otel-v1-apm-span/_doc/phase9-permission-probe",
    ),
    (
        "investigation",
        "OPENSEARCH_INVESTIGATION_WORKER_USERNAME",
        "OPENSEARCH_INVESTIGATION_WORKER_PASSWORD",
        "/aiops-incidents-v1/_search",
        "/aiops-anomalies-v1/_doc/phase9-permission-probe",
    ),
)


async def main() -> None:
    results = []
    for name, username_key, password_key, intended_path, forbidden_path in CHECKS:
        async with httpx.AsyncClient(
            base_url=BASE,
            auth=(os.environ[username_key], os.environ[password_key]),
            verify=False,
            timeout=10,
        ) as client:
            intended = await client.post(intended_path, json={"size": 0})
            forbidden = await client.delete(forbidden_path)
        if intended.status_code != 200:
            raise RuntimeError(f"{name} intended read failed ({intended.status_code})")
        if forbidden.status_code != 403:
            raise RuntimeError(f"{name} forbidden write returned {forbidden.status_code}")
        results.append({"worker": name, "intended_read": 200, "forbidden_write": 403})
    print(json.dumps(results, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
