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
                        "index_patterns": ["aiops-worker-state-v1"],
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
