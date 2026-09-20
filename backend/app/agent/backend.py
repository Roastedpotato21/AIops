import re
from datetime import UTC, datetime, timedelta

from app.incidents.evidence import (
    SECRET_PATTERN,
    EvidenceCandidate,
    bucket_candidate,
    make_evidence_item,
    service_key_from_reference,
    span_snapshot,
)
from app.models.detection import Failure, TimeRange, deterministic_id
from app.models.incidents import (
    DependencySnapshot,
    DocumentLocator,
    ErrorGroupSnapshot,
    LogSnapshot,
    MetricLabel,
    NativeHistogramValue,
    NativeMetricSnapshot,
    NativeScalarValue,
    Provenance,
    QueryLocator,
    QueryParameters,
    TraceLocator,
    TraceSnapshot,
)
from app.models.investigation import (
    DependenciesParams,
    DependencyResults,
    ErrorGroupResults,
    GetIncidentParams,
    GetTraceParams,
    IncidentToolView,
    LogResults,
    MetricResults,
    MetricsParams,
    RelatedErrorsParams,
    SearchLogsParams,
    SearchTracesParams,
    ToolCall,
    ToolContext,
    ToolResponse,
    TraceResults,
    TraceSearchResults,
    TraceSummary,
)
from app.models.telemetry import ServiceReference
from app.repositories.telemetry import TelemetryRepositoryError

SEVERITIES = ["DEBUG", "INFO", "WARN", "ERROR", "FATAL"]
NATIVE_METRIC_NAMES = (
    "aiops.telemetry.heartbeat",
    "demo.http.server.duration",
    "demo.http.server.errors",
    "demo.http.server.requests",
    "process.cpu.utilization",
    "process.memory.usage",
)
NATIVE_LABEL_NAMES = {"http.request.method", "http.route", "http.response.status_code"}
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
DIGIT_PATTERN = re.compile(r"\d+")


class RepositoryToolBackend:
    def __init__(self, incidents, telemetry, *, trace_alias: str) -> None:
        self._incidents = incidents
        self._telemetry = telemetry
        self._trace_alias = trace_alias

    async def get_incident(self, call: ToolCall, context: ToolContext) -> ToolResponse:
        arguments = call.arguments
        assert isinstance(arguments, GetIncidentParams)
        incident = await self._incidents.get_incident(arguments.incident_id)
        if incident is None or incident.latest_evidence_bundle_id is None:
            return self._error(call, context, "not_found", "Incident snapshot is unavailable")
        bundle = await self._incidents.get_bundle(incident.latest_evidence_bundle_id)
        if bundle is None:
            return self._error(call, context, "source_expired", "Evidence bundle is unavailable")
        return self._success(
            call,
            context,
            IncidentToolView(incident=incident, bundle=bundle, evidence_ids=bundle.evidence_ids),
            bundle.evidence_ids,
        )

    async def search_logs(self, call: ToolCall, context: ToolContext) -> ToolResponse:
        arguments = call.arguments
        assert isinstance(arguments, SearchLogsParams)
        try:
            items = []
            partial = False
            start, end = _datetimes(arguments.window)
            severities = SEVERITIES[SEVERITIES.index(arguments.severity_min) :]
            for service in self._services(context, arguments.service_ids):
                for severity in severities:
                    result = await self._telemetry.search_logs(
                        service,
                        start,
                        end,
                        severity=severity,
                        trace_id=arguments.trace_id,
                        text=arguments.text_contains,
                        limit=arguments.limit,
                    )
                    partial = partial or result.metadata.partial or result.metadata.truncated
                    for log in result.items:
                        key = service_key_from_reference(log.service)
                        safe_body = SECRET_PATTERN.sub(r"\1=[REDACTED]", log.body)[:4096]
                        candidate = EvidenceCandidate(
                            evidence_type="log_record",
                            source=DocumentLocator(
                                index=log.source.index,
                                document_id=log.source.document_id,
                            ),
                            service=key,
                            window=TimeRange(
                                start=log.event_time, end=_instant_end(log.event_time)
                            ),
                            summary=f"{log.severity} log: {safe_body[:400]}",
                            snapshot=LogSnapshot(
                                event_time=log.event_time,
                                severity=log.severity,
                                body=safe_body,
                                service=key,
                                trace_id=log.trace_id,
                                span_id=log.span_id,
                                error_type=log.error_type,
                            ),
                            template_id="logs-by-service",
                            index_alias="aiops-logs",
                        )
                        items.append(self._item(context, candidate))
            items = sorted(items, key=lambda item: (item.window.start, item.evidence_id))[
                : arguments.limit
            ]
            await self._incidents.save_evidence_items(items)
            return self._success(
                call,
                context,
                LogResults(items=items),
                [item.evidence_id for item in items],
                partial=partial,
            )
        except TelemetryRepositoryError:
            return self._error(call, context, "unavailable", "Log query failed", True)

    async def search_traces(self, call: ToolCall, context: ToolContext) -> ToolResponse:
        arguments = call.arguments
        assert isinstance(arguments, SearchTracesParams)
        try:
            start, end = _datetimes(arguments.window)
            traces: dict[str, TraceSummary] = {}
            evidence = []
            partial = False
            for service in self._services(context, arguments.service_ids):
                result = await self._telemetry.search_spans(
                    service,
                    start,
                    end,
                    status=arguments.status,
                    min_duration_ms=arguments.min_duration_ms,
                    limit=min(100, arguments.limit * 5),
                )
                partial = partial or result.metadata.partial or result.metadata.truncated
                for span in result.items:
                    candidate = EvidenceCandidate(
                        evidence_type="span",
                        source=DocumentLocator(
                            index=span.source.index, document_id=span.source.document_id
                        ),
                        service=service_key_from_reference(span.service),
                        window=TimeRange(start=span.start_time, end=span.end_time),
                        summary=f"{span.kind} span {span.name[:300]} status={span.status}",
                        snapshot=span_snapshot(span),
                        template_id="trace-search-spans",
                        index_alias=self._trace_alias,
                    )
                    item = self._item(context, candidate)
                    evidence.append(item)
                    existing = traces.get(span.trace_id)
                    ids = (
                        [*existing.evidence_ids, item.evidence_id][:3]
                        if existing
                        else [item.evidence_id]
                    )
                    traces[span.trace_id] = TraceSummary(
                        trace_id=span.trace_id,
                        window=(
                            TimeRange(
                                start=min(existing.window.start, span.start_time),
                                end=max(existing.window.end, span.end_time),
                            )
                            if existing
                            else TimeRange(start=span.start_time, end=span.end_time)
                        ),
                        services=[service_key_from_reference(span.service)],
                        has_error=span.status == "ERROR" or bool(existing and existing.has_error),
                        quality_status="partial" if partial else "complete",
                        evidence_ids=ids,
                        root_duration_ms=(
                            span.duration_ms
                            if span.kind == "SERVER" and span.parent_span_id is None
                            else None
                        ),
                        observed_span_count=None,
                    )
            summaries = sorted(traces.values(), key=lambda item: item.trace_id)[: arguments.limit]
            allowed_ids = {evidence_id for item in summaries for evidence_id in item.evidence_ids}
            evidence = [item for item in evidence if item.evidence_id in allowed_ids]
            await self._incidents.save_evidence_items(evidence)
            return self._success(
                call,
                context,
                TraceSearchResults(items=summaries),
                sorted(allowed_ids),
                partial=partial,
            )
        except TelemetryRepositoryError:
            return self._error(call, context, "unavailable", "Trace search failed", True)

    async def get_trace(self, call: ToolCall, context: ToolContext) -> ToolResponse:
        arguments = call.arguments
        assert isinstance(arguments, GetTraceParams)
        try:
            start, end = _datetimes(context.allowed_window)
            result = await self._telemetry.get_trace(
                arguments.trace_id,
                start_time=start,
                end_time=end,
                max_spans=arguments.max_spans,
            )
            if not result.items:
                return self._error(call, context, "not_found", "Trace is unavailable")
            trace = result.items[0]
            allowed = set(context.allowed_service_ids)
            spans = [
                span_snapshot(span) for span in trace.spans if span.service.service_id in allowed
            ]
            removed = len(trace.spans) - len(spans)
            if not spans:
                return self._error(call, context, "forbidden", "Trace does not intersect scope")
            services = sorted(
                {item.service.service_id: item.service for item in spans}.values(),
                key=lambda service: service.service_id,
            )
            candidate = EvidenceCandidate(
                evidence_type="trace",
                source=TraceLocator(trace_id=trace.trace_id, index_alias=self._trace_alias),
                service=spans[0].service,
                window=TimeRange(start=trace.start_time, end=trace.end_time),
                summary=f"Trace {trace.trace_id} with {len(spans)} authorized spans",
                snapshot=TraceSnapshot(
                    trace_id=trace.trace_id,
                    window=TimeRange(start=trace.start_time, end=trace.end_time),
                    services=services,
                    spans=spans,
                    root_present=trace.root_present,
                    truncated=result.metadata.truncated or removed > 0,
                    missing_parent_count=trace.missing_parent_count,
                    observed_span_count=result.metadata.matched_count,
                ),
                template_id="trace-by-id",
                index_alias=self._trace_alias,
                truncated=result.metadata.partial or result.metadata.truncated or removed > 0,
            )
            item = self._item(context, candidate)
            await self._incidents.save_evidence_items([item])
            return self._success(
                call,
                context,
                TraceResults(trace=item, redacted_out_of_scope_spans=removed),
                [item.evidence_id],
                partial=candidate.truncated,
            )
        except TelemetryRepositoryError:
            return self._error(call, context, "unavailable", "Trace query failed", True)

    async def get_metrics(self, call: ToolCall, context: ToolContext) -> ToolResponse:
        arguments = call.arguments
        assert isinstance(arguments, MetricsParams)
        try:
            buckets = await self._incidents.metric_buckets(
                arguments.service_ids,
                arguments.window.start,
                arguments.window.end,
                limit=arguments.limit,
            )
            items = [
                self._item(
                    context,
                    bucket_candidate(bucket, features=tuple(arguments.features)),
                )
                for bucket in buckets
                if any(getattr(bucket, feature) is not None for feature in arguments.features)
            ]
            native_items = []
            partial = False
            remaining = max(0, arguments.limit - len(items))
            if arguments.include_native and remaining:
                start, end = _datetimes(arguments.window)
                for service in self._services(context, arguments.service_ids):
                    result = await self._telemetry.get_native_metrics(
                        service,
                        start,
                        end,
                        metric_names=NATIVE_METRIC_NAMES,
                        limit=min(20 - len(native_items), remaining - len(native_items)),
                    )
                    partial = partial or result.metadata.partial or result.metadata.truncated
                    for metric in result.items:
                        service_key = service_key_from_reference(metric.service)
                        value = (
                            NativeScalarValue(value=metric.value)
                            if metric.histogram is None
                            else NativeHistogramValue(
                                count=metric.histogram.count,
                                sum=metric.histogram.sum,
                                bounds=metric.histogram.bounds,
                                counts=metric.histogram.counts,
                            )
                        )
                        candidate = EvidenceCandidate(
                            evidence_type="native_metric",
                            source=DocumentLocator(
                                index=metric.source.index,
                                document_id=metric.source.document_id,
                            ),
                            service=service_key,
                            window=TimeRange(
                                start=metric.event_time,
                                end=_instant_end(metric.event_time),
                            ),
                            summary=(
                                f"Native metric {metric.name} ({metric.metric_type}, "
                                f"unit={metric.unit})"
                            ),
                            snapshot=NativeMetricSnapshot(
                                service=service_key,
                                name=metric.name,
                                unit=metric.unit,
                                window=TimeRange(
                                    start=metric.event_time,
                                    end=_instant_end(metric.event_time),
                                ),
                                metric_type=metric.metric_type,
                                temporality=metric.temporality,
                                attribute_labels=[
                                    MetricLabel(key=key, value=label)
                                    for key, label in sorted(metric.labels.items())
                                    if key in NATIVE_LABEL_NAMES
                                ][:16],
                                value=value,
                            ),
                            template_id="native-metrics-by-service",
                            index_alias="aiops-metrics-raw",
                            include_native=True,
                        )
                        native_items.append(self._item(context, candidate))
                        if len(native_items) >= min(20, remaining):
                            break
                    if len(native_items) >= min(20, remaining):
                        break
            all_items = [*items, *native_items]
            await self._incidents.save_evidence_items(all_items)
            return self._success(
                call,
                context,
                MetricResults(buckets=items, native_points=native_items),
                [item.evidence_id for item in all_items],
                partial=partial,
            )
        except TelemetryRepositoryError:
            return self._error(call, context, "unavailable", "Metric query failed", True)

    async def get_service_dependencies(self, call: ToolCall, context: ToolContext) -> ToolResponse:
        arguments = call.arguments
        assert isinstance(arguments, DependenciesParams)
        service = self._services(context, [arguments.service_id])[0]
        try:
            start, end = _datetimes(arguments.window)
            result = await self._telemetry.get_service_dependencies(
                service, start, end, limit=arguments.limit
            )
            items = []
            for edge in result.items:
                candidate = EvidenceCandidate(
                    evidence_type="dependency_edge",
                    source=QueryLocator(
                        query_id=deterministic_id("query", [edge.edge_id]),
                        index_alias=self._trace_alias,
                    ),
                    service=service_key_from_reference(service),
                    window=arguments.window,
                    summary=(
                        f"Observed dependency {edge.source_service.name} "
                        f"to {edge.target_service.name}"
                    ),
                    snapshot=DependencySnapshot(edge=edge),
                    template_id="dependencies-by-service",
                    index_alias=self._trace_alias,
                )
                items.append(self._item(context, candidate))
            await self._incidents.save_evidence_items(items)
            return self._success(
                call,
                context,
                DependencyResults(edges=items),
                [item.evidence_id for item in items],
                partial=result.metadata.partial or result.metadata.truncated,
            )
        except TelemetryRepositoryError:
            return self._error(call, context, "unavailable", "Dependency query failed", True)

    async def find_related_errors(self, call: ToolCall, context: ToolContext) -> ToolResponse:
        arguments = call.arguments
        assert isinstance(arguments, RelatedErrorsParams)
        log_call = ToolCall(
            call_id=call.call_id,
            name="search_logs",
            arguments=SearchLogsParams(
                service_ids=arguments.service_ids,
                window=arguments.window,
                trace_id=arguments.trace_id,
                severity_min="ERROR",
                limit=min(30, arguments.limit * 3),
            ),
        )
        logs = await self.search_logs(log_call, context)
        if not isinstance(logs.result, LogResults):
            return logs
        groups: dict[str, list] = {}
        group_values: dict[str, tuple] = {}
        for item in logs.result.items:
            snapshot = item.snapshot
            if not isinstance(snapshot, LogSnapshot):
                continue
            error_type = snapshot.error_type or "unknown"
            template = _error_template(snapshot.body)
            fingerprint = deterministic_id(
                "errorgroup", [item.service.service_id, error_type, template, "1.0.0"]
            )
            groups.setdefault(fingerprint, []).append(item)
            group_values[fingerprint] = (item.service, error_type, template)
        ranked = sorted(groups, key=lambda key: (-len(groups[key]), key))[: arguments.limit]
        group_items = []
        samples = []
        for fingerprint in ranked:
            observed = groups[fingerprint]
            sample_ids = [item.evidence_id for item in observed[:3]]
            service, error_type, template = group_values[fingerprint]
            candidate = EvidenceCandidate(
                evidence_type="error_group",
                source=QueryLocator(
                    query_id=deterministic_id(
                        "query",
                        [fingerprint, arguments.window.start, arguments.window.end],
                    ),
                    index_alias="aiops-logs",
                ),
                service=service,
                window=arguments.window,
                summary=f"{error_type}: {template} ({len(observed)} observed)",
                snapshot=ErrorGroupSnapshot(
                    fingerprint=fingerprint,
                    service=service,
                    window=arguments.window,
                    error_type=error_type,
                    message_template=template,
                    count=len(observed),
                    sample_evidence_ids=sample_ids,
                ),
                template_id="related-errors-by-service",
                index_alias="aiops-logs",
                truncated=logs.status == "partial",
            )
            group_items.append(self._item(context, candidate))
            samples.extend(observed[:3])
        unique_samples = list({item.evidence_id: item for item in samples}.values())[:30]
        await self._incidents.save_evidence_items(group_items)
        evidence_ids = [
            *[item.evidence_id for item in group_items],
            *[item.evidence_id for item in unique_samples],
        ]
        return self._success(
            call,
            context,
            ErrorGroupResults(groups=group_items, samples=unique_samples),
            evidence_ids,
            partial=logs.status == "partial",
        )

    def _services(self, context: ToolContext, service_ids: list[str]) -> list[ServiceReference]:
        incident = getattr(self, "_current_incident", None)
        if incident is None:
            raise TelemetryRepositoryError("unavailable", retryable=False)
        by_id = {item.service_id: item for item in incident.affected_services}
        return [
            ServiceReference(
                namespace=by_id[item].namespace,
                environment=by_id[item].environment,
                name=by_id[item].name,
            )
            for item in service_ids
        ]

    async def bind_incident(self, incident_id: str) -> None:
        self._current_incident = await self._incidents.get_incident(incident_id)

    def _item(self, context: ToolContext, candidate: EvidenceCandidate):
        return make_evidence_item(
            context.incident_id,
            candidate,
            created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

    def _success(
        self, call, context, result, evidence_ids, *, partial: bool = False
    ) -> ToolResponse:
        status = "partial" if partial else ("empty" if not evidence_ids else "ok")
        return ToolResponse(
            call_id=call.call_id,
            status=status,
            result=result,
            failure=None,
            provenance=_provenance(call, context, len(evidence_ids), partial),
            quality_reasons=["truncated"] if partial else [],
            evidence_ids=evidence_ids,
        )

    def _error(self, call, context, code, message, retryable: bool = False) -> ToolResponse:
        return ToolResponse(
            call_id=call.call_id,
            status="error",
            result=None,
            failure=Failure(code=code, message=message, retryable=retryable),
            provenance=_provenance(call, context, 0, False),
            quality_reasons=["tool_failure"],
            evidence_ids=[],
        )


def _provenance(call, context, count, truncated):
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    arguments = call.arguments
    return Provenance(
        query_id=deterministic_id("query", [context.job_id, str(call.call_id), call.name]),
        template_id=f"tool-{call.name}",
        template_version="1.0.0",
        parameters=QueryParameters(
            service_ids=getattr(arguments, "service_ids", context.allowed_service_ids),
            window=getattr(arguments, "window", context.allowed_window),
            trace_id=getattr(arguments, "trace_id", None),
            severity_min=getattr(arguments, "severity_min", None),
            features=getattr(arguments, "features", []),
            incident_id=context.incident_id,
            max_spans=getattr(arguments, "max_spans", None),
            text_contains=getattr(arguments, "text_contains", None),
            status=getattr(arguments, "status", None),
            min_duration_ms=getattr(arguments, "min_duration_ms", None),
            limit=getattr(arguments, "limit", max(1, count)),
            direction=getattr(arguments, "direction", None),
            include_native=getattr(arguments, "include_native", False),
        ),
        retrieved_at=now,
        source_cutoff=now,
        returned_count=count,
        matched_count=count,
        truncated=truncated,
    )


def _datetimes(window):
    return (
        datetime.fromisoformat(window.start.replace("Z", "+00:00")),
        datetime.fromisoformat(window.end.replace("Z", "+00:00")),
    )


def _error_template(value: str) -> str:
    redacted = SECRET_PATTERN.sub(r"\1=[REDACTED]", value)
    normalized = DIGIT_PATTERN.sub("<n>", UUID_PATTERN.sub("<uuid>", redacted))
    return " ".join(normalized.split())[:512] or "unknown error"


def _instant_end(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed + timedelta(microseconds=1)).isoformat().replace("+00:00", "Z")
