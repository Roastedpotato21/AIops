import asyncio
import json
import os
from datetime import UTC, datetime

import httpx
from app.detection.registry import AGGREGATION_VERSION, CONFIG_VERSION, registered_specs

BASE = os.environ.get("OPENSEARCH_URL", "https://opensearch:9200")
AUTH = (os.environ["OPENSEARCH_ADMIN_USERNAME"], os.environ["OPENSEARCH_ADMIN_PASSWORD"])


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def compatible(native: dict, expected: dict) -> bool:
    exact_keys = (
        "time_field",
        "indices",
        "feature_attributes",
        "detection_interval",
        "window_delay",
        "shingle_size",
        "result_index",
    )
    if any(native.get(key) != expected.get(key) for key in exact_keys):
        return False
    # OpenSearch rewrites term/exists queries with boost/value wrappers when
    # storing them, so compare their required semantics rather than raw JSON.
    native_filter = json.dumps(native.get("filter_query", {}), sort_keys=True)
    required = (
        expected["filter_query"]["bool"]["filter"][0]["term"]["service.service_id"],
        "aggregation_version",
        "1.0.0",
        "eligible_for_detection",
        "finalized_at",
    )
    return all(str(value).lower() in native_filter.lower() for value in required)


async def checked(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> httpx.Response:
    response = await client.request(method, path, **kwargs)
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Detector provisioning {method} {path} failed ({response.status_code})")
    return response


async def main() -> None:
    delay = int(os.environ.get("DETECTOR_WINDOW_DELAY_MINUTES", "3"))
    async with httpx.AsyncClient(base_url=BASE, auth=AUTH, verify=False, timeout=10) as client:
        existing_response = await client.request(
            "GET",
            "/_plugins/_anomaly_detection/detectors/_search",
            json={"size": 100, "query": {"match_all": {}}},
        )
        if existing_response.status_code == 404:
            existing_hits = []
        elif existing_response.status_code == 200:
            existing_hits = existing_response.json().get("hits", {}).get("hits", [])
        else:
            raise RuntimeError(
                f"Detector registry search failed ({existing_response.status_code})"
            )
        existing = {
            hit.get("_source", {}).get("name"): (hit.get("_id"), hit.get("_source", {}))
            for hit in existing_hits
        }
        summaries: list[str] = []
        for spec in registered_specs(delay):
            found = existing.get(spec.name)
            if found is None:
                created = await checked(
                    client,
                    "POST",
                    "/_plugins/_anomaly_detection/detectors",
                    json=spec.body,
                )
                detector_id = created.json().get("_id")
                if not isinstance(detector_id, str):
                    raise RuntimeError("Detector create response omitted its identifier")
            else:
                detector_id, native = found
                if not isinstance(detector_id, str):
                    raise RuntimeError("Existing detector omitted its identifier")
                if not compatible(native, spec.body):
                    raise RuntimeError(f"Existing detector {spec.name} has incompatible configuration")
            profile = await checked(
                client,
                "GET",
                f"/_plugins/_anomaly_detection/detectors/{detector_id}/_profile?_all=true",
            )
            profile_text = str(profile.json()).lower()
            if not any(value in profile_text for value in ("running", "initializing", "init")):
                start = await client.post(
                    f"/_plugins/_anomaly_detection/detectors/{detector_id}/_start"
                )
                if start.status_code not in (200, 201, 400):
                    raise RuntimeError(f"Detector start failed ({start.status_code})")
            now = utc_now()
            await checked(
                client,
                "PUT",
                f"/aiops-worker-state-v1/_doc/{spec.registration_id}?refresh=wait_for",
                json={
                    "schema_version": "1.0.0",
                    "record_kind": "detector_registration",
                    "registration_id": spec.registration_id,
                    "service": spec.service.model_dump(),
                    "feature": spec.feature,
                    "native_detector_id": detector_id,
                    "detector_name": spec.name,
                    "config_version": CONFIG_VERSION,
                    "aggregation_version": AGGREGATION_VERSION,
                    "config_sha256": spec.config_sha256,
                    "state": "active",
                    "activated_at": now,
                    "retired_at": None,
                    "updated_at": now,
                    "last_error": None,
                },
            )
            summaries.append(f"{spec.service.name}/{spec.feature}: {detector_id}")
    print("Provisioned six idempotent Phase 5 detectors.")
    for summary in summaries:
        print(summary)


if __name__ == "__main__":
    asyncio.run(main())
