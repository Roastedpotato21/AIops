import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

BASE = os.environ.get("OPENSEARCH_URL", "https://opensearch:9200")
ADMIN = (os.environ["OPENSEARCH_ADMIN_USERNAME"], os.environ["OPENSEARCH_ADMIN_PASSWORD"])
SPAN_TEMPLATE = Path("infra/opensearch/otel-v1-apm-span-index-standard-template.json")


async def request(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> httpx.Response:
    response = await client.request(method, path, **kwargs)
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Bootstrap request {method} {path} failed with {response.status_code}")
    return response


async def ensure_read_alias(
    client: httpx.AsyncClient,
    *,
    template_name: str,
    index_pattern: str,
    alias: str,
) -> None:
    await request(
        client,
        "PUT",
        f"/_template/{template_name}",
        json={
            "order": 100,
            "index_patterns": [index_pattern],
            "aliases": {alias: {}},
        },
    )
    response = await request(
        client,
        "GET",
        f"/_cat/indices/{index_pattern}?format=json&h=index",
    )
    indices = sorted(
        item["index"]
        for item in response.json()
        if isinstance(item, dict) and isinstance(item.get("index"), str)
    )
    if indices:
        await request(
            client,
            "POST",
            "/_aliases",
            json={
                "actions": [
                    {"add": {"index": index_name, "alias": alias}}
                    for index_name in indices
                ]
            },
        )


async def ensure_product_index(
    client: httpx.AsyncClient,
    *,
    index: str,
    alias: str,
    mappings: dict[str, object],
) -> None:
    if (await client.head(f"/{index}")).status_code == 404:
        await request(
            client,
            "PUT",
            f"/{index}",
            json={
                "settings": {"index.number_of_shards": 1, "index.number_of_replicas": 0},
                "mappings": {"dynamic": "strict", "properties": mappings},
                "aliases": {alias: {"is_write_index": True}},
            },
        )
    else:
        await request(
            client,
            "POST",
            "/_aliases",
            json={"actions": [{"add": {"index": index, "alias": alias, "is_write_index": True}}]},
        )


SERVICE_MAPPING = {
    "service_id": {"type": "keyword"},
    "namespace": {"type": "keyword"},
    "environment": {"type": "keyword"},
    "name": {"type": "keyword"},
}

TIME_RANGE_MAPPING = {
    "start": {"type": "date_nanos"},
    "end": {"type": "date_nanos"},
}

FAILURE_MAPPING = {
    "code": {"type": "keyword"},
    "message": {"type": "keyword", "index": False},
    "retryable": {"type": "boolean"},
}

SERVICE_METRIC_MAPPINGS = {
    "schema_version": {"type": "keyword"},
    "bucket_id": {"type": "keyword"},
    "service": {"type": "object", "dynamic": "strict", "properties": SERVICE_MAPPING},
    "window": {"type": "object", "dynamic": "strict", "properties": TIME_RANGE_MAPPING},
    "bucket_time": {"type": "date"},
    "request_count": {"type": "long"},
    "error_count": {"type": "long"},
    "error_rate": {"type": "double"},
    "latency_mean_ms": {"type": "double"},
    "latency_p95_ms": {"type": "double"},
    "source_count": {"type": "long"},
    "invalid_span_count": {"type": "long"},
    "late_span_count": {"type": "long"},
    "quality_status": {"type": "keyword"},
    "quality_reasons": {"type": "keyword"},
    "eligible_for_detection": {"type": "boolean"},
    "source_kind": {"type": "keyword"},
    "aggregation_version": {"type": "keyword"},
    "sampling_fraction": {"type": "double"},
    "computed_at": {"type": "date"},
    "finalized_at": {"type": "date"},
    "source_visible_through": {"type": "date"},
}

ANOMALY_MAPPINGS = {
    "schema_version": {"type": "keyword"},
    "anomaly_id": {"type": "keyword"},
    "detector_id": {"type": "keyword"},
    "detector_name": {"type": "keyword"},
    "detector_config_version": {"type": "keyword"},
    "service": {"type": "object", "dynamic": "strict", "properties": SERVICE_MAPPING},
    "feature": {"type": "keyword"},
    "feature_value": {"type": "double"},
    "input_bucket_id": {"type": "keyword"},
    "detector_window": {"type": "object", "dynamic": "strict", "properties": TIME_RANGE_MAPPING},
    "affected_window": {"type": "object", "dynamic": "strict", "properties": TIME_RANGE_MAPPING},
    "execution_started_at": {"type": "date"},
    "execution_ended_at": {"type": "date"},
    "anomaly_grade": {"type": "double"},
    "detector_confidence": {"type": "double"},
    "result_status": {"type": "keyword"},
    "error_reason": {"type": "keyword", "index": False},
    "source": {
        "type": "object",
        "dynamic": "strict",
        "properties": {"index": {"type": "keyword"}, "document_id": {"type": "keyword"}},
    },
    "observed_at": {"type": "date"},
    "processing_state": {"type": "keyword"},
    "processing": {
        "type": "object",
        "dynamic": "strict",
        "properties": {
            "processing_state": {"type": "keyword"},
            "disposition": {"type": "keyword"},
            "decision_reason": {"type": "keyword", "index": False},
            "incident_id": {"type": "keyword"},
            "policy_version": {"type": "keyword"},
            "processed_at": {"type": "date"},
            "last_error": {
                "type": "object",
                "dynamic": "strict",
                "properties": FAILURE_MAPPING,
            },
        },
    },
}

WORKER_STATE_ADDITIONS = {
    "worker_state_id": {"type": "keyword"},
    "role": {"type": "keyword"},
    "partition": {"type": "keyword"},
    "cursor": {
        "type": "object",
        "dynamic": "strict",
        "properties": {
            "kind": {"type": "keyword"},
            "service_id": {"type": "keyword"},
            "finalized_through": {"type": "date"},
            "aggregation_version": {"type": "keyword"},
        },
    },
    "owner_id": {"type": "keyword"},
    "heartbeat_at": {"type": "date"},
    "status": {"type": "keyword"},
    "last_error": {
        "type": "object",
        "dynamic": "strict",
        "properties": FAILURE_MAPPING,
    },
    "updated_at": {"type": "date"},
    "registration_id": {"type": "keyword"},
    "service": {"type": "object", "dynamic": "strict", "properties": SERVICE_MAPPING},
    "feature": {"type": "keyword"},
    "native_detector_id": {"type": "keyword"},
    "detector_name": {"type": "keyword"},
    "config_version": {"type": "keyword"},
    "aggregation_version": {"type": "keyword"},
    "config_sha256": {"type": "keyword"},
    "activated_at": {"type": "date"},
    "retired_at": {"type": "date"},
}


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, auth=ADMIN, verify=False, timeout=10.0) as client:
        span_template = json.loads(SPAN_TEMPLATE.read_text(encoding="utf-8"))
        span_template["index_patterns"] = ["otel-v1-apm-span-*"]
        span_template["settings"] = {
            "index.opendistro.index_state_management.rollover_alias": "otel-v1-apm-span"
        }
        await request(
            client,
            "PUT",
            "/_template/otel-v1-apm-span-index-template",
            json=span_template,
        )
        alias_response = await client.get("/_alias/otel-v1-apm-span")
        if alias_response.status_code == 200:
            aliases = alias_response.json()
            write_indices = [
                name
                for name, value in aliases.items()
                if value.get("aliases", {})
                .get("otel-v1-apm-span", {})
                .get("is_write_index")
            ]
            if len(write_indices) != 1:
                raise RuntimeError("Native trace alias must have exactly one write index")
            write_index = write_indices[0]
            mapping = (await request(client, "GET", f"/{write_index}/_mapping")).json()
            properties = mapping[write_index].get("mappings", {}).get("properties", {})
            if "resource" not in properties:
                count = (await request(client, "GET", f"/{write_index}/_count")).json()["count"]
                if count:
                    raise RuntimeError(
                        "Incompatible native trace mapping contains data; refusing automatic rollover"
                    )
                await request(client, "POST", "/otel-v1-apm-span/_rollover", json={})
        elif alias_response.status_code != 404:
            raise RuntimeError(
                f"Native trace alias inspection failed with {alias_response.status_code}"
            )

        await ensure_read_alias(
            client,
            template_name="aiops-logs-read-alias-v1",
            index_pattern="aiops-logs-*",
            alias="aiops-logs",
        )
        await ensure_read_alias(
            client,
            template_name="aiops-metrics-read-alias-v1",
            index_pattern="aiops-metrics-raw-*",
            alias="aiops-metrics-raw",
        )
        await ensure_product_index(
            client,
            index="aiops-service-metrics-v1-000001",
            alias="aiops-service-metrics-v1",
            mappings=SERVICE_METRIC_MAPPINGS,
        )
        await ensure_product_index(
            client,
            index="aiops-anomalies-v1-000001",
            alias="aiops-anomalies-v1",
            mappings=ANOMALY_MAPPINGS,
        )
        await request(
            client,
            "PUT",
            "/aiops-anomalies-v1-000001/_mapping",
            json={"properties": ANOMALY_MAPPINGS},
        )

        await request(
            client,
            "PUT",
            "/_plugins/_security/api/roles/aiops_data_prepper_role",
            json={
                # Data Prepper's documented minimum for its OpenSearch sink.
                "cluster_permissions": [
                    "cluster_all",
                    "indices:admin/template/get",
                    "indices:admin/template/put",
                    "indices:admin/data_stream/get",
                    "indices:data/write/bulk*",
                    "cluster:admin/opendistro/ism/*",
                ],
                "index_permissions": [
                    {
                        "index_patterns": [
                            "aiops-logs-*",
                            "aiops-metrics-raw-*",
                            "otel-v1-apm-span*",
                            "otel-v1-apm-service-map*",
                        ],
                        "allowed_actions": [
                            "indices_all",
                            "indices:admin/opensearch/ism/*",
                        ],
                    },
                    {
                        "index_patterns": [".opendistro-ism-config"],
                        "allowed_actions": ["indices_all"],
                    },
                    {
                        "index_patterns": ["*"],
                        "allowed_actions": ["manage_aliases"],
                    },
                ],
                "tenant_permissions": [],
            },
        )
        await request(
            client,
            "PUT",
            f"/_plugins/_security/api/internalusers/{os.environ['OPENSEARCH_DATA_PREPPER_USERNAME']}",
            json={
                "password": os.environ["OPENSEARCH_DATA_PREPPER_PASSWORD"],
                "opendistro_security_roles": ["aiops_data_prepper_role"],
            },
        )
        await request(
            client,
            "PUT",
            "/_plugins/_security/api/roles/aiops_api_role",
            json={
                "cluster_permissions": ["cluster_monitor"],
                "index_permissions": [
                    {
                        "index_patterns": [
                            "aiops-worker-state-v1",
                            "aiops-service-metrics-v1*",
                            "aiops-anomalies-v1*",
                            "opensearch-ad-plugin-result-aiops-v1*",
                            "aiops-logs*",
                            "aiops-metrics-raw*",
                            "otel-v1-apm-span*",
                            "otel-v1-apm-service-map*",
                        ],
                        "allowed_actions": ["read"],
                    }
                ],
                "tenant_permissions": [],
            },
        )
        await request(
            client,
            "PUT",
            f"/_plugins/_security/api/internalusers/{os.environ['OPENSEARCH_API_USERNAME']}",
            json={
                "password": os.environ["OPENSEARCH_API_PASSWORD"],
                "opendistro_security_roles": ["aiops_api_role"],
            },
        )
        await request(
            client,
            "PUT",
            "/_plugins/_security/api/roles/aiops_worker_role",
            json={
                "cluster_permissions": ["cluster_monitor", "indices:data/write/bulk*"],
                "index_permissions": [
                    {
                        "index_patterns": [
                            "otel-v1-apm-span*",
                            "aiops-service-metrics-v1*",
                            "aiops-anomalies-v1*",
                            "aiops-worker-state-v1",
                            "opensearch-ad-plugin-result-aiops-v1*",
                        ],
                        "allowed_actions": [
                            "indices_all",
                        ],
                    }
                ],
                "tenant_permissions": [],
            },
        )
        await request(
            client,
            "PUT",
            f"/_plugins/_security/api/internalusers/{os.environ['OPENSEARCH_WORKER_USERNAME']}",
            json={
                "password": os.environ["OPENSEARCH_WORKER_PASSWORD"],
                "opendistro_security_roles": ["aiops_worker_role"],
            },
        )
        await request(
            client,
            "PUT",
            "/_plugins/_security/api/rolesmapping/aiops_worker_role",
            json={
                "backend_roles": [],
                "hosts": [],
                "users": [os.environ["OPENSEARCH_WORKER_USERNAME"]],
            },
        )
        await request(
            client,
            "PUT",
            "/aiops-worker-state-v1",
            json={
                "settings": {"index.number_of_shards": 1, "index.number_of_replicas": 0},
                "mappings": {
                    "dynamic": "strict",
                    "properties": {
                        "schema_version": {"type": "keyword"},
                        "record_kind": {"type": "keyword"},
                        "bootstrap_id": {"type": "keyword"},
                        "release_id": {"type": "keyword"},
                        "contract_version": {"type": "keyword"},
                        "state": {"type": "keyword"},
                        "completed_at": {"type": "date"},
                    },
                },
            },
        ) if (await client.head("/aiops-worker-state-v1")).status_code == 404 else None
        worker_mapping = (
            await request(client, "GET", "/aiops-worker-state-v1/_mapping")
        )
        additions = dict(WORKER_STATE_ADDITIONS)
        current_properties = (
            worker_mapping.json().get("aiops-worker-state-v1", {})
            .get("mappings", {})
            .get("properties", {})
        )
        # An earlier local Phase 5 development run briefly introduced a
        # scalar last_error mapping. Preserve that non-production volume
        # without destructive reset; clean bootstraps use the fixed object.
        if current_properties.get("last_error", {}).get("type") == "keyword":
            additions.pop("last_error")
        await request(
            client,
            "PUT",
            "/aiops-worker-state-v1/_mapping",
            json={"properties": additions},
        )
        completed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        await request(
            client,
            "PUT",
            "/aiops-worker-state-v1/_doc/platform-bootstrap-v1?refresh=wait_for",
            json={
                "schema_version": "1.0.0",
                "record_kind": "bootstrap",
                "bootstrap_id": "platform-bootstrap-v1",
                "release_id": "phase1-foundation",
                "contract_version": "1.0.0",
                "state": "ready",
                "completed_at": completed_at,
            },
        )
    print("Bootstrap completed idempotently.")


if __name__ == "__main__":
    asyncio.run(main())
