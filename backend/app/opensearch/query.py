from collections.abc import Mapping
from typing import Any, Literal

import httpx

from app.config import Settings


class OpenSearchQueryFailure(RuntimeError):
    def __init__(
        self,
        code: Literal["invalid_query", "unauthorized", "unavailable"],
    ) -> None:
        super().__init__("OpenSearch telemetry query failed")
        self.code = code


class OpenSearchQueryClient:
    def __init__(self, settings: Settings) -> None:
        verify: bool | str = (
            settings.opensearch_ca_file if settings.opensearch_verify_tls else False
        )
        self._client = httpx.AsyncClient(
            base_url=settings.opensearch_url,
            auth=(settings.opensearch_username, settings.opensearch_password),
            verify=verify,
            timeout=settings.opensearch_query_timeout_seconds,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def search(self, index: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            response = await self._client.post(f"/{index}/_search", json=body)
        except httpx.HTTPError as exc:
            raise OpenSearchQueryFailure("unavailable") from exc
        if response.status_code in (401, 403):
            raise OpenSearchQueryFailure("unauthorized")
        if response.status_code == 400:
            raise OpenSearchQueryFailure("invalid_query")
        if response.is_error:
            raise OpenSearchQueryFailure("unavailable")
        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenSearchQueryFailure("unavailable") from exc
        if not isinstance(payload, Mapping):
            raise OpenSearchQueryFailure("unavailable")
        return payload
