from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, TypeVar

from app.config import Settings
from app.models.telemetry import (
    DependencyEdge,
    NativeMetric,
    QueryMetadata,
    QueryReason,
    ServiceReference,
    TelemetryLog,
    TelemetryQueryResult,
    TelemetrySpan,
    TelemetryTrace,
    utc_timestamp_to_ns,
)
from app.opensearch.query import OpenSearchQueryFailure
from app.telemetry.adapters import (
    MalformedTelemetryDocument,
    dependency_edge_id,
    map_log_document,
    map_metric_document,
    map_span_document,
)

MAX_QUERY_SECONDS = 24 * 60 * 60
MAX_DEPENDENCY_SECONDS = 60 * 60
MAX_RESULTS = 200
DEPENDENCY_SPAN_FETCH_LIMIT = 1_000
TRACE_LOOKBACK = timedelta(hours=24)


class SearchClient(Protocol):
    async def search(
        self,
        index: str,
        body: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


class TelemetryRepositoryError(RuntimeError):
    def __init__(
        self,
        code: Literal["invalid_argument", "unauthorized", "unavailable"],
        *,
        retryable: bool,
    ) -> None:
        super().__init__(f"Telemetry repository {code.replace('_', ' ')}")
        self.code = code
        self.retryable = retryable


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _service_filters(service: ServiceReference) -> list[dict[str, Any]]:
    return [
        {"term": {"resource.attributes.service.namespace": service.namespace}},
        {"term": {"resource.attributes.deployment.environment.name": service.environment}},
        {"term": {"resource.attributes.service.name": service.name}},
    ]


def _dynamic_service_filters(service: ServiceReference) -> list[dict[str, Any]]:
    return [
        {"term": {"resource.attributes.service.namespace.keyword": service.namespace}},
        {
            "term": {
                "resource.attributes.deployment.environment.name.keyword": (
                    service.environment
                )
            }
        },
        {"term": {"resource.attributes.service.name.keyword": service.name}},
    ]


def _sort(field: str) -> list[dict[str, Any]]:
    return [
        {field: {"order": "asc", "unmapped_type": "date_nanos"}},
        {"traceId": {"order": "asc", "unmapped_type": "keyword"}},
        {"spanId": {"order": "asc", "unmapped_type": "keyword"}},
    ]


T = TypeVar("T")


class TelemetryRepository:
    def __init__(
        self,
        client: SearchClient,
        settings: Settings,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client = client
        self._logs_index = settings.logs_read_alias
        self._spans_index = settings.spans_read_alias
        self._metrics_index = settings.metrics_read_alias
        self._clock = clock

    def _window(
        self,
        start_time: datetime,
        end_time: datetime,
        *,
        max_seconds: int = MAX_QUERY_SECONDS,
    ) -> tuple[str, str]:
        if start_time.tzinfo is None or end_time.tzinfo is None:
            raise TelemetryRepositoryError("invalid_argument", retryable=False)
        start = start_time.astimezone(UTC)
        end = end_time.astimezone(UTC)
        now = self._clock().astimezone(UTC)
        if start >= end or end - start > timedelta(seconds=max_seconds):
            raise TelemetryRepositoryError("invalid_argument", retryable=False)
        if end > now + timedelta(seconds=30):
            raise TelemetryRepositoryError("invalid_argument", retryable=False)
        return _utc(start), _utc(end)

    @staticmethod
    def _limit(limit: int, maximum: int = MAX_RESULTS) -> int:
        if isinstance(limit, bool) or not 1 <= limit <= maximum:
            raise TelemetryRepositoryError("invalid_argument", retryable=False)
        return limit

    async def _query(
        self,
        index: str,
        body: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        try:
            return await self._client.search(index, body)
        except OpenSearchQueryFailure as exc:
            if exc.code == "unauthorized":
                raise TelemetryRepositoryError("unauthorized", retryable=False) from None
            if exc.code == "invalid_query":
                raise TelemetryRepositoryError("unavailable", retryable=False) from None
            raise TelemetryRepositoryError("unavailable", retryable=True) from None
        except TelemetryRepositoryError:
            raise
        except Exception:
            raise TelemetryRepositoryError("unavailable", retryable=True) from None

    @staticmethod
    def _hits(
        response: Mapping[str, Any],
    ) -> tuple[list[Mapping[str, Any]], int | None, bool]:
        try:
            hits_object = response["hits"]
            raw_hits = hits_object["hits"]
            total_object = hits_object.get("total")
            shards = response.get("_shards", {})
        except (KeyError, TypeError, AttributeError) as exc:
            raise TelemetryRepositoryError("unavailable", retryable=True) from exc
        if not isinstance(raw_hits, list) or not isinstance(shards, Mapping):
            raise TelemetryRepositoryError("unavailable", retryable=True)
        if not all(isinstance(item, Mapping) for item in raw_hits):
            raise TelemetryRepositoryError("unavailable", retryable=True)
        matched_count = None
        total_partial = False
        if isinstance(total_object, int):
            matched_count = total_object
        elif isinstance(total_object, Mapping):
            value = total_object.get("value")
            relation = total_object.get("relation")
            if isinstance(value, int) and not isinstance(value, bool):
                matched_count = value
            total_partial = relation != "eq"
        partial = bool(
            response.get("timed_out")
            or shards.get("failed", 0)
            or total_partial
        )
        return raw_hits, matched_count, partial

    @staticmethod
    def _metadata(
        *,
        returned_count: int,
        matched_count: int | None,
        partial: bool,
        truncated: bool,
        malformed_count: int = 0,
        duplicate_count: int = 0,
        duplicate_conflict_count: int = 0,
        malformed_reason: QueryReason = "query_partial",
    ) -> QueryMetadata:
        reasons: list[QueryReason] = []
        if duplicate_conflict_count:
            reasons.append("duplicate_conflict")
        if malformed_count:
            reasons.append(malformed_reason)
        if partial:
            reasons.append("query_partial")
        if truncated:
            reasons.append("truncated")
        reasons = list(dict.fromkeys(reasons))
        return QueryMetadata(
            partial=bool(reasons),
            truncated=truncated,
            reasons=reasons,
            returned_count=returned_count,
            matched_count=matched_count,
            malformed_count=malformed_count,
            duplicate_count=duplicate_count,
            duplicate_conflict_count=duplicate_conflict_count,
        )

    @staticmethod
    def _map_hits(
        hits: Sequence[Mapping[str, Any]],
        adapter: Callable[[Mapping[str, Any]], T],
    ) -> tuple[list[T], int]:
        items: list[T] = []
        malformed_count = 0
        for hit in hits:
            try:
                items.append(adapter(hit))
            except MalformedTelemetryDocument:
                malformed_count += 1
        return items, malformed_count

    async def search_logs(
        self,
        service: ServiceReference,
        start_time: datetime,
        end_time: datetime,
        *,
        severity: Literal["DEBUG", "INFO", "WARN", "ERROR", "FATAL"] | None = None,
        trace_id: str | None = None,
        text: str | None = None,
        limit: int = 100,
    ) -> TelemetryQueryResult[TelemetryLog]:
        start, end = self._window(start_time, end_time)
        limit = self._limit(limit)
        filters: list[dict[str, Any]] = [
            {"range": {"time": {"gte": start, "lt": end}}},
            *_dynamic_service_filters(service),
        ]
        if severity is not None:
            filters.append({"term": {"severityText.keyword": severity}})
        if trace_id is not None:
            filters.append({"term": {"traceId.keyword": trace_id}})
        must = []
        if text is not None:
            if not 1 <= len(text) <= 256:
                raise TelemetryRepositoryError("invalid_argument", retryable=False)
            must.append({"match_phrase": {"body": text}})
        response = await self._query(
            self._logs_index,
            {
                "size": limit + 1,
                "track_total_hits": True,
                "query": {"bool": {"filter": filters, "must": must}},
                "sort": [
                    {"time": {"order": "asc", "unmapped_type": "date"}},
                    {"traceId.keyword": {"order": "asc", "unmapped_type": "keyword"}},
                    {"spanId.keyword": {"order": "asc", "unmapped_type": "keyword"}},
                ],
            },
        )
        hits, matched_count, source_partial = self._hits(response)
        items, malformed = self._map_hits(hits, map_log_document)
        items.sort(
            key=lambda item: (
                utc_timestamp_to_ns(item.event_time),
                item.source.index,
                item.source.document_id,
            )
        )
        truncated = len(items) > limit or (matched_count is not None and matched_count > limit)
        items = items[:limit]
        metadata = self._metadata(
            returned_count=len(items),
            matched_count=matched_count,
            partial=source_partial,
            truncated=truncated,
            malformed_count=malformed,
        )
        return TelemetryQueryResult[TelemetryLog](items=items, metadata=metadata)

    def _span_query(
        self,
        start: str,
        end: str,
        *,
        service: ServiceReference | None,
        trace_id: str | None,
        status: Literal["error", "ok"] | None,
        min_duration_ms: float | None,
        kind: Literal["SERVER", "CLIENT", "INTERNAL", "PRODUCER", "CONSUMER"] | None,
        size: int,
    ) -> dict[str, Any]:
        filters: list[dict[str, Any]] = [
            {"range": {"endTime": {"gte": start, "lt": end}}},
        ]
        if service is not None:
            filters.extend(_service_filters(service))
        if kind is not None:
            filters.append({"term": {"kind": f"SPAN_KIND_{kind}"}})
        if trace_id is not None:
            filters.append({"term": {"traceId": trace_id}})
        if min_duration_ms is not None:
            if isinstance(min_duration_ms, bool) or min_duration_ms < 0:
                raise TelemetryRepositoryError("invalid_argument", retryable=False)
            filters.append(
                {"range": {"durationInNanos": {"gte": int(min_duration_ms * 1_000_000)}}}
            )
        must_not: list[dict[str, Any]] = []
        should: list[dict[str, Any]] = []
        minimum_should_match = 0
        if status == "error":
            should = [
                {"term": {"status.code": 2}},
                {"range": {"attributes.http.status_code": {"gte": 500}}},
                {"range": {"attributes.http.response.status_code": {"gte": 500}}},
            ]
            minimum_should_match = 1
        elif status == "ok":
            must_not = [
                {"term": {"status.code": 2}},
                {"range": {"attributes.http.status_code": {"gte": 500}}},
                {"range": {"attributes.http.response.status_code": {"gte": 500}}},
            ]
        return {
            "size": size,
            "track_total_hits": True,
            "query": {
                "bool": {
                    "filter": filters,
                    "should": should,
                    "minimum_should_match": minimum_should_match,
                    "must_not": must_not,
                }
            },
            "sort": _sort("endTime"),
        }

    @staticmethod
    def _deduplicate_spans(
        spans: Sequence[TelemetrySpan],
    ) -> tuple[list[TelemetrySpan], int, int]:
        selected: dict[tuple[str, str, str, str], TelemetrySpan] = {}
        duplicate_count = 0
        conflict_count = 0
        for span in sorted(
            spans,
            key=lambda item: (
                item.source.index,
                item.source.document_id,
            ),
        ):
            key = (
                span.service.namespace,
                span.service.environment,
                span.trace_id,
                span.span_id,
            )
            existing = selected.get(key)
            if existing is None:
                selected[key] = span
            elif existing.content_sha256 == span.content_sha256:
                duplicate_count += 1
            else:
                conflict_count += 1
        return list(selected.values()), duplicate_count, conflict_count

    async def _search_spans(
        self,
        start: str,
        end: str,
        *,
        service: ServiceReference | None,
        trace_id: str | None,
        status: Literal["error", "ok"] | None,
        min_duration_ms: float | None,
        kind: Literal["SERVER", "CLIENT", "INTERNAL", "PRODUCER", "CONSUMER"] | None,
        limit: int,
    ) -> tuple[list[TelemetrySpan], QueryMetadata]:
        response = await self._query(
            self._spans_index,
            self._span_query(
                start,
                end,
                service=service,
                trace_id=trace_id,
                status=status,
                min_duration_ms=min_duration_ms,
                kind=kind,
                size=limit + 1,
            ),
        )
        hits, matched_count, source_partial = self._hits(response)
        mapped, malformed = self._map_hits(hits, map_span_document)
        spans, duplicate_count, conflict_count = self._deduplicate_spans(mapped)
        spans.sort(
            key=lambda item: (
                utc_timestamp_to_ns(item.end_time),
                item.trace_id,
                item.span_id,
                item.source.index,
            )
        )
        truncated = len(spans) > limit or (matched_count is not None and matched_count > limit)
        spans = spans[:limit]
        metadata = self._metadata(
            returned_count=len(spans),
            matched_count=matched_count,
            partial=source_partial,
            truncated=truncated,
            malformed_count=malformed,
            duplicate_count=duplicate_count,
            duplicate_conflict_count=conflict_count,
            malformed_reason="invalid_span",
        )
        return spans, metadata

    async def search_spans(
        self,
        service: ServiceReference | None,
        start_time: datetime,
        end_time: datetime,
        *,
        trace_id: str | None = None,
        status: Literal["error", "ok"] | None = None,
        min_duration_ms: float | None = None,
        kind: Literal["SERVER", "CLIENT", "INTERNAL", "PRODUCER", "CONSUMER"] | None = None,
        limit: int = 100,
    ) -> TelemetryQueryResult[TelemetrySpan]:
        start, end = self._window(start_time, end_time)
        limit = self._limit(limit)
        spans, metadata = await self._search_spans(
            start,
            end,
            service=service,
            trace_id=trace_id,
            status=status,
            min_duration_ms=min_duration_ms,
            kind=kind,
            limit=limit,
        )
        return TelemetryQueryResult[TelemetrySpan](items=spans, metadata=metadata)

    @staticmethod
    def _order_trace(spans: Sequence[TelemetrySpan]) -> tuple[list[TelemetrySpan], bool, int]:
        by_id = {span.span_id: span for span in spans}
        children: dict[str, list[TelemetrySpan]] = defaultdict(list)
        roots = []
        missing_parent_count = 0
        for span in spans:
            if span.parent_span_id is None:
                roots.append(span)
            elif span.parent_span_id in by_id:
                children[span.parent_span_id].append(span)
            else:
                missing_parent_count += 1
        def key(item: TelemetrySpan) -> tuple[int, str]:
            return (utc_timestamp_to_ns(item.start_time), item.span_id)
        roots.sort(key=key)
        for values in children.values():
            values.sort(key=key)
        ordered: list[TelemetrySpan] = []
        visited: set[str] = set()

        def visit(span: TelemetrySpan) -> None:
            if span.span_id in visited:
                return
            visited.add(span.span_id)
            ordered.append(span)
            for child in children.get(span.span_id, []):
                visit(child)

        for root in roots:
            visit(root)
        for span in sorted(spans, key=key):
            visit(span)
        return ordered, bool(roots), missing_parent_count

    async def get_trace(
        self,
        trace_id: str,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        max_spans: int = 200,
    ) -> TelemetryQueryResult[TelemetryTrace]:
        if not isinstance(trace_id, str) or len(trace_id) != 32:
            raise TelemetryRepositoryError("invalid_argument", retryable=False)
        end_value = end_time or self._clock()
        start_value = start_time or end_value - TRACE_LOOKBACK
        start, end = self._window(start_value, end_value)
        max_spans = self._limit(max_spans)
        spans, span_metadata = await self._search_spans(
            start,
            end,
            service=None,
            trace_id=trace_id,
            status=None,
            min_duration_ms=None,
            kind=None,
            limit=max_spans,
        )
        if not spans:
            return TelemetryQueryResult[TelemetryTrace](
                items=[],
                metadata=span_metadata.model_copy(update={"returned_count": 0}),
            )
        ordered, root_present, missing_parent_count = self._order_trace(spans)
        services = {
            span.service.service_id: ServiceReference(
                namespace=span.service.namespace,
                environment=span.service.environment,
                name=span.service.name,
            )
            for span in ordered
        }
        trace = TelemetryTrace(
            trace_id=trace_id,
            spans=ordered,
            services=[services[key] for key in sorted(services)],
            start_time=min(
                ordered, key=lambda item: utc_timestamp_to_ns(item.start_time)
            ).start_time,
            end_time=max(ordered, key=lambda item: utc_timestamp_to_ns(item.end_time)).end_time,
            root_present=root_present,
            missing_parent_count=missing_parent_count,
            has_error=any(
                span.status == "ERROR"
                or (span.http_status_code is not None and span.http_status_code >= 500)
                for span in ordered
            ),
        )
        reasons = list(span_metadata.reasons)
        if missing_parent_count and "invalid_span" not in reasons:
            reasons.append("invalid_span")
        metadata = span_metadata.model_copy(
            update={
                "partial": bool(reasons),
                "reasons": reasons,
                "returned_count": 1,
            }
        )
        return TelemetryQueryResult[TelemetryTrace](items=[trace], metadata=metadata)

    async def get_native_metrics(
        self,
        service: ServiceReference,
        start_time: datetime,
        end_time: datetime,
        *,
        metric_names: Sequence[str] | None = None,
        limit: int = 100,
    ) -> TelemetryQueryResult[NativeMetric]:
        start, end = self._window(start_time, end_time)
        limit = self._limit(limit)
        filters: list[dict[str, Any]] = [
            {"range": {"time": {"gte": start, "lt": end}}},
            *_dynamic_service_filters(service),
        ]
        if metric_names is not None:
            names = list(dict.fromkeys(metric_names))
            if not 1 <= len(names) <= 20 or any(
                not isinstance(name, str) or not 1 <= len(name) <= 128 for name in names
            ):
                raise TelemetryRepositoryError("invalid_argument", retryable=False)
            filters.append({"terms": {"name.keyword": names}})
        response = await self._query(
            self._metrics_index,
            {
                "size": limit + 1,
                "track_total_hits": True,
                "query": {"bool": {"filter": filters}},
                "sort": _sort("time"),
            },
        )
        hits, matched_count, source_partial = self._hits(response)
        items, malformed = self._map_hits(hits, map_metric_document)
        items.sort(
            key=lambda item: (
                utc_timestamp_to_ns(item.event_time),
                item.name,
                item.source.index,
                item.source.document_id,
            )
        )
        truncated = len(items) > limit or (matched_count is not None and matched_count > limit)
        items = items[:limit]
        metadata = self._metadata(
            returned_count=len(items),
            matched_count=matched_count,
            partial=source_partial,
            truncated=truncated,
            malformed_count=malformed,
        )
        return TelemetryQueryResult[NativeMetric](items=items, metadata=metadata)

    async def get_service_dependencies(
        self,
        service: ServiceReference | None,
        start_time: datetime,
        end_time: datetime,
        *,
        limit: int = 50,
    ) -> TelemetryQueryResult[DependencyEdge]:
        start, end = self._window(
            start_time,
            end_time,
            max_seconds=MAX_DEPENDENCY_SECONDS,
        )
        limit = self._limit(limit, 100)
        spans, source_metadata = await self._search_spans(
            start,
            end,
            service=None,
            trace_id=None,
            status=None,
            min_duration_ms=None,
            kind=None,
            limit=DEPENDENCY_SPAN_FETCH_LIMIT,
        )
        by_trace: dict[str, list[TelemetrySpan]] = defaultdict(list)
        for span in spans:
            by_trace[span.trace_id].append(span)
        supporting: dict[tuple[str, str], set[str]] = defaultdict(set)
        references: dict[str, ServiceReference] = {}
        for trace_id, trace_spans in by_trace.items():
            servers_by_parent = {
                span.parent_span_id: span
                for span in trace_spans
                if span.kind == "SERVER" and span.parent_span_id is not None
            }
            for client_span in (span for span in trace_spans if span.kind == "CLIENT"):
                server_span = servers_by_parent.get(client_span.span_id)
                if server_span is None:
                    continue
                source_reference = ServiceReference(
                    namespace=client_span.service.namespace,
                    environment=client_span.service.environment,
                    name=client_span.service.name,
                )
                target_reference = ServiceReference(
                    namespace=server_span.service.namespace,
                    environment=server_span.service.environment,
                    name=server_span.service.name,
                )
                if (
                    source_reference.namespace != target_reference.namespace
                    or source_reference.environment != target_reference.environment
                ):
                    continue
                if service is not None and service not in (source_reference, target_reference):
                    continue
                source_id = client_span.service.service_id
                target_id = server_span.service.service_id
                references[source_id] = source_reference
                references[target_id] = target_reference
                supporting[(source_id, target_id)].add(trace_id)
        observed_at = _utc(self._clock())
        edges = []
        for (source_id, target_id), trace_ids in supporting.items():
            source_reference = references[source_id]
            target_reference = references[target_id]
            edges.append(
                DependencyEdge(
                    edge_id=dependency_edge_id(
                        source_reference,
                        target_reference,
                        start,
                        end,
                    ),
                    source_service=source_reference,
                    target_service=target_reference,
                    window_start=start,
                    window_end=end,
                    observed_trace_count=(
                        None
                        if source_metadata.partial or source_metadata.truncated
                        else len(trace_ids)
                    ),
                    sample_trace_ids=sorted(trace_ids)[:5],
                    observed_at=observed_at,
                    source_kind="trace_reconstruction",
                )
            )
        edges.sort(
            key=lambda item: (
                item.source_service.namespace,
                item.source_service.environment,
                item.source_service.name,
                item.target_service.name,
                item.edge_id,
            )
        )
        truncated = len(edges) > limit or source_metadata.truncated
        edges = edges[:limit]
        reasons = list(source_metadata.reasons)
        if truncated and "truncated" not in reasons:
            reasons.append("truncated")
        metadata = QueryMetadata(
            partial=bool(reasons),
            truncated=truncated,
            reasons=reasons,
            returned_count=len(edges),
            matched_count=len(supporting) if not source_metadata.partial else None,
            malformed_count=source_metadata.malformed_count,
            duplicate_count=source_metadata.duplicate_count,
            duplicate_conflict_count=source_metadata.duplicate_conflict_count,
        )
        return TelemetryQueryResult[DependencyEdge](items=edges, metadata=metadata)
