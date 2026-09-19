from dataclasses import dataclass
from typing import Literal

import httpx

from app.config import Settings


@dataclass(frozen=True)
class DependencyResult:
    state: Literal["pass", "fail"]
    reason_code: Literal["unreachable", "unauthorized", "bootstrap_pending"] | None = None


class OpenSearchReadinessClient:
    def __init__(self, settings: Settings) -> None:
        verify: bool | str = (
            settings.opensearch_ca_file if settings.opensearch_verify_tls else False
        )
        self._client = httpx.AsyncClient(
            base_url=settings.opensearch_url,
            auth=(settings.opensearch_username, settings.opensearch_password),
            verify=verify,
            timeout=5.0,
        )
        self._bootstrap_index = settings.bootstrap_index
        self._bootstrap_document_id = settings.bootstrap_document_id

    async def close(self) -> None:
        await self._client.aclose()

    async def cluster(self) -> DependencyResult:
        try:
            response = await self._client.get("/_cluster/health")
        except httpx.HTTPError:
            return DependencyResult("fail", "unreachable")
        if response.status_code in (401, 403):
            return DependencyResult("fail", "unauthorized")
        if response.is_error:
            return DependencyResult("fail", "unreachable")
        if response.json().get("status") == "red":
            return DependencyResult("fail", "unreachable")
        return DependencyResult("pass")

    async def bootstrap(self) -> DependencyResult:
        try:
            response = await self._client.get(
                f"/{self._bootstrap_index}/_doc/{self._bootstrap_document_id}"
            )
        except httpx.HTTPError:
            return DependencyResult("fail", "unreachable")
        if response.status_code in (401, 403):
            return DependencyResult("fail", "unauthorized")
        if response.status_code == 404:
            return DependencyResult("fail", "bootstrap_pending")
        if response.is_error:
            return DependencyResult("fail", "unreachable")
        source = response.json().get("_source", {})
        if source.get("state") != "ready" or source.get("contract_version") != "1.0.0":
            return DependencyResult("fail", "bootstrap_pending")
        return DependencyResult("pass")
