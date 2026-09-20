from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol, cast

from app.models.detection import Failure
from app.models.investigation import (
    DependenciesParams,
    GetIncidentParams,
    GetTraceParams,
    MetricsParams,
    RelatedErrorsParams,
    SearchLogsParams,
    SearchTracesParams,
    ToolCall,
    ToolContext,
    ToolResponse,
)
from app.models.telemetry import utc_timestamp_to_ns


class ToolBackend(Protocol):
    async def get_incident(self, call: ToolCall, context: ToolContext) -> ToolResponse: ...
    async def search_logs(self, call: ToolCall, context: ToolContext) -> ToolResponse: ...
    async def search_traces(self, call: ToolCall, context: ToolContext) -> ToolResponse: ...
    async def get_trace(self, call: ToolCall, context: ToolContext) -> ToolResponse: ...
    async def get_metrics(self, call: ToolCall, context: ToolContext) -> ToolResponse: ...
    async def get_service_dependencies(
        self, call: ToolCall, context: ToolContext
    ) -> ToolResponse: ...
    async def find_related_errors(self, call: ToolCall, context: ToolContext) -> ToolResponse: ...


class ToolBudgetExceeded(RuntimeError):
    pass


class ToolRegistry:
    NAMES = (
        "get_incident",
        "search_logs",
        "search_traces",
        "get_trace",
        "get_metrics",
        "get_service_dependencies",
        "find_related_errors",
    )

    def __init__(self, backend: ToolBackend, *, max_calls: int = 8) -> None:
        if not 1 <= max_calls <= 8:
            raise ValueError("tool-call budget must be between one and eight")
        self._backend = backend
        self._max_calls = max_calls
        self._used = 0

    @property
    def used(self) -> int:
        return self._used

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResponse:
        self._used += 1
        if self._used > self._max_calls:
            raise ToolBudgetExceeded("tool-call budget exhausted")
        failure = self._validate(call, context)
        if failure is not None:
            return _error_response(call, context, failure)
        methods: dict[str, Callable[[ToolCall, ToolContext], Awaitable[ToolResponse]]] = {
            "get_incident": self._backend.get_incident,
            "search_logs": self._backend.search_logs,
            "search_traces": self._backend.search_traces,
            "get_trace": self._backend.get_trace,
            "get_metrics": self._backend.get_metrics,
            "get_service_dependencies": self._backend.get_service_dependencies,
            "find_related_errors": self._backend.find_related_errors,
        }
        return await methods[call.name](call, context)

    @staticmethod
    def _validate(call: ToolCall, context: ToolContext) -> Failure | None:
        now = datetime.now(UTC)
        deadline = datetime.fromisoformat(context.deadline_at.replace("Z", "+00:00"))
        if now >= deadline:
            return Failure(
                code="timeout", message="Investigation deadline reached", retryable=False
            )
        arguments = call.arguments
        if isinstance(arguments, GetIncidentParams):
            if arguments.incident_id != context.incident_id:
                return _forbidden("Incident is outside the authorized scope")
            return None
        if isinstance(arguments, GetTraceParams):
            return None
        if isinstance(arguments, DependenciesParams):
            service_ids = [arguments.service_id]
            window = arguments.window
        else:
            scoped = cast(
                SearchLogsParams | SearchTracesParams | MetricsParams | RelatedErrorsParams,
                arguments,
            )
            service_ids = scoped.service_ids
            window = scoped.window
        if not set(service_ids) <= set(context.allowed_service_ids):
            return _forbidden("Service is outside the authorized scope")
        if (
            utc_timestamp_to_ns(window.start) < utc_timestamp_to_ns(context.allowed_window.start)
            or utc_timestamp_to_ns(window.end) > utc_timestamp_to_ns(context.allowed_window.end)
            or utc_timestamp_to_ns(window.end) - utc_timestamp_to_ns(window.start)
            > 30 * 60 * 1_000_000_000
        ):
            return _forbidden("Time window is outside the authorized scope")
        if getattr(arguments, "cursor", None) is not None:
            return Failure(
                code="invalid_argument",
                message="Continuation cursor is not valid for this snapshot",
                retryable=False,
            )
        return None


def _forbidden(message: str) -> Failure:
    return Failure(code="forbidden", message=message, retryable=False)


def _error_response(call: ToolCall, context: ToolContext, failure: Failure) -> ToolResponse:
    from app.models.detection import TimeRange, deterministic_id
    from app.models.incidents import Provenance, QueryParameters

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    query_id = deterministic_id("query", [context.job_id, str(call.call_id), call.name])
    return ToolResponse(
        call_id=call.call_id,
        status="error",
        result=None,
        failure=failure,
        provenance=Provenance(
            query_id=query_id,
            template_id=f"tool-{call.name}",
            template_version="1.0.0",
            parameters=QueryParameters(
                service_ids=context.allowed_service_ids,
                window=TimeRange(
                    start=context.allowed_window.start, end=context.allowed_window.end
                ),
                features=[],
                incident_id=context.incident_id,
                limit=1,
                include_native=False,
            ),
            retrieved_at=now,
            source_cutoff=now,
            returned_count=0,
            matched_count=None,
            truncated=False,
        ),
        quality_reasons=["tool_failure"],
        evidence_ids=[],
    )
