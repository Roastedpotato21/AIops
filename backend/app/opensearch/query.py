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

    async def request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> Mapping[str, Any] | None:
        try:
            response = await self._client.request(method, path, json=body, params=params)
        except httpx.HTTPError as exc:
            raise OpenSearchQueryFailure("unavailable") from exc
        if response.status_code == 404 and allow_not_found:
            return None
        if response.status_code in (401, 403):
            raise OpenSearchQueryFailure("unauthorized")
        if response.status_code in (400, 409):
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

    async def search(self, index: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = await self.request("POST", f"/{index}/_search", body=body)
        if payload is None:
            raise OpenSearchQueryFailure("unavailable")
        return payload

    async def get_document(self, index: str, document_id: str) -> Mapping[str, Any] | None:
        return await self.request(
            "GET",
            f"/{index}/_doc/{document_id}",
            allow_not_found=True,
        )

    async def put_document(
        self,
        index: str,
        document_id: str,
        document: Mapping[str, Any],
        *,
        refresh: bool = False,
        if_seq_no: int | None = None,
        if_primary_term: int | None = None,
    ) -> Mapping[str, Any]:
        params: dict[str, Any] = {"refresh": "wait_for"} if refresh else {}
        if if_seq_no is not None and if_primary_term is not None:
            params.update(
                {
                    "if_seq_no": if_seq_no,
                    "if_primary_term": if_primary_term,
                }
            )
        payload = await self.request(
            "PUT",
            f"/{index}/_doc/{document_id}",
            body=document,
            params=params,
        )
        if payload is None:
            raise OpenSearchQueryFailure("unavailable")
        return payload
