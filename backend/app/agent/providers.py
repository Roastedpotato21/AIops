import json
from collections.abc import Sequence
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

import httpx
from pydantic import SecretStr, ValidationError

from app.models.detection import Failure
from app.models.investigation import (
    GenerationRequest,
    GenerationResponse,
    InvestigationReport,
    ProviderUsage,
    TextMessage,
    ToolCall,
    ToolRequestMessage,
    ToolResultMessage,
)


class ReasoningProvider(Protocol):
    provider_id: str

    async def generate(self, request: GenerationRequest) -> GenerationResponse: ...


class DeterministicTestProvider:
    provider_id = "deterministic-test-provider"

    def __init__(self, responses: Sequence[GenerationResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.requests.append(request)
        if not self._responses:
            return GenerationResponse(
                kind="failure",
                failure=Failure(
                    code="invalid_output",
                    message="Deterministic test provider has no scripted response",
                    retryable=False,
                ),
                usage=ProviderUsage(input_tokens=0, output_tokens=0),
            )
        return self._responses.pop(0)


class UnavailableProvider:
    """Safe runtime provider used when external reasoning is not configured."""

    provider_id = "disabled"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        return _provider_failure("Reasoning provider is not configured", retryable=False)


class OpenAIResponsesProvider:
    """OpenAI Responses API adapter. Construction requires an explicitly supplied key."""

    provider_id = "openai"
    _endpoint = "https://api.openai.com/v1/responses"

    def __init__(self, api_key: SecretStr, *, timeout_seconds: float = 30) -> None:
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
            timeout=timeout_seconds,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        body = {
            "model": request.model_id,
            "store": False,
            "input": [part for item in request.messages for part in _message_parts(item)],
            "tools": [
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": _argument_schema(tool.parameter_contract),
                    "strict": True,
                }
                for tool in request.tools
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "investigation_report",
                    "schema": InvestigationReport.model_json_schema(),
                    "strict": True,
                }
            },
            "max_output_tokens": request.remaining_output_tokens,
        }
        try:
            response = await self._client.post(self._endpoint, json=body)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return _provider_failure("Provider request failed", retryable=True)
        usage = ProviderUsage(
            input_tokens=payload.get("usage", {}).get("input_tokens"),
            output_tokens=payload.get("usage", {}).get("output_tokens"),
            provider_request_id=payload.get("id"),
        )
        calls = []
        for item in payload.get("output", []):
            if item.get("type") != "function_call":
                continue
            try:
                calls.append(
                    ToolCall.model_validate(
                        {
                            "call_id": str(
                                uuid5(
                                    NAMESPACE_URL,
                                    "openai-tool-call:"
                                    + str(item.get("call_id"))
                                    + ":"
                                    + str(item.get("name")),
                                )
                            ),
                            "name": item["name"],
                            "arguments": json.loads(item["arguments"]),
                        }
                    )
                )
            except (KeyError, TypeError, ValueError, ValidationError):
                return _provider_failure("Provider returned an invalid tool request")
        if calls:
            return GenerationResponse(kind="tool_requests", tool_calls=calls, usage=usage)
        output_text = payload.get("output_text")
        if not isinstance(output_text, str):
            texts = [
                content.get("text")
                for item in payload.get("output", [])
                for content in item.get("content", [])
                if content.get("type") == "output_text"
            ]
            output_text = "".join(item for item in texts if isinstance(item, str))
        try:
            report = InvestigationReport.model_validate_json(output_text)
        except (TypeError, ValidationError):
            return _provider_failure("Provider returned an invalid report")
        return GenerationResponse(kind="report", report=report, usage=usage)


def _message_parts(message):
    if isinstance(message, TextMessage):
        return [{"role": message.role, "content": message.text}]
    if isinstance(message, ToolRequestMessage):
        return [
            {
                "type": "function_call",
                "call_id": str(call.call_id),
                "name": call.name,
                "arguments": call.arguments.model_dump_json(),
            }
            for call in message.calls
        ]
    if isinstance(message, ToolResultMessage):
        return [
            {
                "type": "function_call_output",
                "call_id": str(message.response.call_id),
                "output": message.response.model_dump_json(),
            }
        ]
    raise TypeError("unsupported provider message")


def _argument_schema(name: str) -> dict:
    from app.models.investigation import (
        DependenciesParams,
        GetIncidentParams,
        GetTraceParams,
        MetricsParams,
        RelatedErrorsParams,
        SearchLogsParams,
        SearchTracesParams,
    )

    models = {
        "GetIncidentParams": GetIncidentParams,
        "SearchLogsParams": SearchLogsParams,
        "SearchTracesParams": SearchTracesParams,
        "GetTraceParams": GetTraceParams,
        "MetricsParams": MetricsParams,
        "DependenciesParams": DependenciesParams,
        "RelatedErrorsParams": RelatedErrorsParams,
    }
    return models[name].model_json_schema()


def _provider_failure(message: str, *, retryable: bool = False) -> GenerationResponse:
    return GenerationResponse(
        kind="failure",
        failure=Failure(code="invalid_output", message=message, retryable=retryable),
        usage=ProviderUsage(),
    )
