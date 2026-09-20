import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Any

import httpx
from app.detection.adapters import NativeResultError, normalize_native_result
from app.detection.registry import registered_specs
from app.models.detection import ServiceMetricBucket

BASE = os.environ.get("OPENSEARCH_URL", "https://opensearch:9200")
AUTH = (os.environ["OPENSEARCH_ADMIN_USERNAME"], os.environ["OPENSEARCH_ADMIN_PASSWORD"])
RESULT_INDEX = "opensearch-ad-plugin-result-aiops-v1"


async def search(client: httpx.AsyncClient, index: str, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(f"/{index}/_search", json=body)
    if response.status_code == 404:
        return {"hits": {"hits": []}}
    if response.status_code != 200:
        raise RuntimeError(f"Phase 5 inspection query failed ({response.status_code})")
    return response.json()


async def native_results(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    path = (
        f"/_plugins/_anomaly_detection/detectors/results/_search/{RESULT_INDEX}"
        "?only_query_custom_result_index=true"
    )
    body = {"size": 200, "sort": [{"execution_end_time": {"order": "asc"}}]}
    response = await client.post(path, json=body)
    if response.status_code == 404:
        return []
    if response.status_code != 200:
        raise RuntimeError(f"Native result inspection failed ({response.status_code})")
    return response.json().get("hits", {}).get("hits", [])


async def main() -> None:
    observed = datetime.now(UTC)
    async with httpx.AsyncClient(base_url=BASE, auth=AUTH, verify=False, timeout=10) as client:
        bucket_response = await search(
            client,
            "aiops-service-metrics-v1",
            {"size": 60, "sort": [{"bucket_time": "desc"}], "query": {"match_all": {}}},
        )
        buckets = [
            ServiceMetricBucket.model_validate(hit["_source"])
            for hit in bucket_response.get("hits", {}).get("hits", [])
        ]
        registration_response = await search(
            client,
            "aiops-worker-state-v1",
            {
                "size": 20,
                "query": {"term": {"record_kind": "detector_registration"}},
                "sort": [{"detector_name": "asc"}],
            },
        )
        registrations = [hit["_source"] for hit in registration_response["hits"]["hits"]]
        specs = {spec.name: spec for spec in registered_specs()}
        by_id = {
            registration["native_detector_id"]: specs[registration["detector_name"]]
            for registration in registrations
            if registration.get("detector_name") in specs
        }
        states = []
        for detector_id, spec in by_id.items():
            response = await client.get(
                f"/_plugins/_anomaly_detection/detectors/{detector_id}/_profile?_all=true"
            )
            profile = response.json() if response.status_code == 200 else {}
            native_state = str(profile.get("state", "")).upper()
            native_error = profile.get("error")
            if (
                isinstance(native_error, str)
                and "no data in current window" in native_error.lower()
            ):
                state = "insufficient_data"
            elif response.status_code != 200 or native_error:
                state = "failed"
            elif native_state == "RUNNING":
                state = "ready"
            elif native_state in {"INIT", "INITIALIZING"}:
                state = "warming_up"
            else:
                state = "warming_up"
            states.append(
                {
                    "service": spec.service.name,
                    "feature": spec.feature,
                    "state": state,
                    "native_state": native_state or None,
                    "init_progress": profile.get("init_progress"),
                }
            )

        normalized = []
        for hit in await native_results(client):
            native = hit.get("_source", {})
            spec = by_id.get(native.get("detector_id"))
            if spec is None:
                continue
            candidates = [
                bucket
                for bucket in buckets
                if bucket.service.service_id == spec.service.service_id
                and int(datetime.fromisoformat(bucket.bucket_time.replace("Z", "+00:00")).timestamp() * 1000)
                >= native.get("data_start_time", 0)
                and int(datetime.fromisoformat(bucket.bucket_time.replace("Z", "+00:00")).timestamp() * 1000)
                < native.get("data_end_time", 0)
            ]
            try:
                result = normalize_native_result(
                    source_index=hit["_index"],
                    source_id=hit["_id"],
                    native=native,
                    spec=spec,
                    matching_buckets=candidates,
                    observed_at=observed,
                )
            except NativeResultError:
                continue
            response = await client.put(
                f"/aiops-anomalies-v1/_doc/{result.anomaly_id}?refresh=wait_for",
                json=result.model_dump(),
            )
            if response.status_code not in (200, 201):
                raise RuntimeError(
                    f"Normalized result write failed ({response.status_code}): "
                    f"{response.text[:800]}"
                )
            normalized.append(result)

    print(
        json.dumps(
            {
                "buckets": [
                    {
                        "service": bucket.service.name,
                        "window": bucket.window.model_dump(),
                        "requests": bucket.request_count,
                        "errors": bucket.error_count,
                        "error_rate": bucket.error_rate,
                        "p95_ms": bucket.latency_p95_ms,
                        "quality": bucket.quality_status,
                        "eligible": bucket.eligible_for_detection,
                    }
                    for bucket in buckets[:15]
                ],
                "detectors": states,
                "normalized_results": [
                    {
                        "service": result.service.name,
                        "feature": result.feature,
                        "status": result.result_status,
                        "grade": result.anomaly_grade,
                        "confidence": result.detector_confidence,
                        "bucket_id": result.input_bucket_id,
                    }
                    for result in normalized[-20:]
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
