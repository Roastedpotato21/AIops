import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.models.detection import (
    NormalizedAnomaly,
    ServiceKey,
    ServiceMetricBucket,
    TimeRange,
    deterministic_id,
)
from app.models.incidents import (
    AnomalySnapshot,
    DependencySnapshot,
    DocumentLocator,
    EvidenceBundle,
    EvidenceItem,
    EvidenceSnapshot,
    LogSnapshot,
    MetricBucketSnapshot,
    Provenance,
    QueryLocator,
    QueryParameters,
    ReasonCode,
    SourceLocator,
    SpanSnapshot,
    TraceLocator,
    TraceSnapshot,
)
from app.models.telemetry import ServiceReference, TelemetryService
from app.repositories.telemetry import TelemetryRepository, TelemetryRepositoryError

ITEM_LIMIT = 262_144
BUNDLE_LIMIT = 2_097_152
ITEM_COUNT_LIMIT = 300
REDACTION_VERSION = "1.0.0"
SECRET_PATTERN = re.compile(r"(?i)(authorization|password|token|secret|api[_-]?key)\s*[:=]\s*\S+")


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _utc(now: datetime) -> str:
    return now.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class EvidenceCandidate:
    evidence_type: str
    source: SourceLocator
    service: ServiceKey
    window: TimeRange
    summary: str
    snapshot: EvidenceSnapshot
    template_id: str
    index_alias: str
    matched_count: int | None = 1
    truncated: bool = False


def service_key_from_reference(service: ServiceReference | TelemetryService) -> ServiceKey:
    return ServiceKey(
        service_id=(
            service.service_id
            if isinstance(service, TelemetryService)
            else deterministic_id("svc", [service.namespace, service.environment, service.name])
        ),
        namespace=service.namespace,
        environment=service.environment,
        name=service.name,
    )


def span_snapshot(span) -> SpanSnapshot:
    return SpanSnapshot(
        trace_id=span.trace_id,
        span_id=span.span_id,
        parent_span_id=span.parent_span_id,
        service=service_key_from_reference(span.service),
        name=span.name[:256],
        span_kind=span.kind,
        start_time=span.start_time,
        end_time=span.end_time,
        duration_ms=span.duration_ms,
        status=span.status,
        http_status_code=span.http_status_code,
        http_route=span.http_route,
    )


class TelemetryEvidenceCollector:
    def __init__(self, repository: TelemetryRepository, *, trace_alias: str) -> None:
        self._repository = repository
        self._trace_alias = trace_alias

    async def __call__(self, incident, anomaly: NormalizedAnomaly) -> list[EvidenceCandidate]:
        start = datetime.fromisoformat(anomaly.affected_window.start.replace("Z", "+00:00"))
        affected_end = datetime.fromisoformat(anomaly.affected_window.end.replace("Z", "+00:00"))
        end = min(affected_end + timedelta(minutes=2), datetime.now(UTC))
        start -= timedelta(minutes=5)
        service = ServiceReference(
            namespace=incident.primary_service.namespace,
            environment=incident.primary_service.environment,
            name=incident.primary_service.name,
        )
        window = TimeRange(start=_utc(start), end=_utc(end))
        candidates: list[EvidenceCandidate] = []
        try:
            logs = await self._repository.search_logs(
                service, start, end, severity="ERROR", limit=50
            )
            for log in logs.items:
                body = SECRET_PATTERN.sub(r"\1=[REDACTED]", log.body)[:4096]
                candidates.append(
                    EvidenceCandidate(
                        evidence_type="log_record",
                        source=DocumentLocator(
                            index=log.source.index, document_id=log.source.document_id
                        ),
                        service=service_key_from_reference(log.service),
                        window=TimeRange(
                            start=log.event_time,
                            end=_instant_end(log.event_time),
                        ),
                        summary=f"{log.severity} log: {body[:400]}",
                        snapshot=LogSnapshot(
                            event_time=log.event_time,
                            severity=log.severity,
                            body=body,
                            service=service_key_from_reference(log.service),
                            trace_id=log.trace_id,
                            span_id=log.span_id,
                            error_type=log.error_type,
                        ),
                        template_id="logs-by-service",
                        index_alias="aiops-logs",
                        matched_count=logs.metadata.matched_count,
                        truncated=logs.metadata.truncated or logs.metadata.partial,
                    )
                )
            spans = await self._repository.search_spans(
                service, start, end, status="error", limit=30
            )
            for span in spans.items:
                candidates.append(
                    EvidenceCandidate(
                        evidence_type="span",
                        source=DocumentLocator(
                            index=span.source.index, document_id=span.source.document_id
                        ),
                        service=service_key_from_reference(span.service),
                        window=TimeRange(start=span.start_time, end=span.end_time),
                        summary=(
                            f"{span.kind} span {span.name[:300]} status={span.status} "
                            f"duration_ms={span.duration_ms:.3f}"
                        ),
                        snapshot=span_snapshot(span),
                        template_id="error-spans-by-service",
                        index_alias=self._trace_alias,
                        matched_count=spans.metadata.matched_count,
                        truncated=spans.metadata.truncated or spans.metadata.partial,
                    )
                )
            for trace_id in list(dict.fromkeys(item.trace_id for item in spans.items))[:5]:
                result = await self._repository.get_trace(
                    trace_id, start_time=start, end_time=end, max_spans=200
                )
                if not result.items:
                    continue
                trace = result.items[0]
                trace_spans = [span_snapshot(item) for item in trace.spans]
                candidates.append(
                    EvidenceCandidate(
                        evidence_type="trace",
                        source=TraceLocator(trace_id=trace.trace_id, index_alias=self._trace_alias),
                        service=incident.primary_service,
                        window=TimeRange(start=trace.start_time, end=trace.end_time),
                        summary=f"Trace {trace.trace_id} with {len(trace_spans)} bounded spans",
                        snapshot=TraceSnapshot(
                            trace_id=trace.trace_id,
                            window=TimeRange(start=trace.start_time, end=trace.end_time),
                            services=[service_key_from_reference(item) for item in trace.services],
                            spans=trace_spans,
                            root_present=trace.root_present,
                            truncated=result.metadata.truncated,
                            missing_parent_count=trace.missing_parent_count,
                            observed_span_count=result.metadata.matched_count,
                        ),
                        template_id="trace-by-id",
                        index_alias=self._trace_alias,
                        matched_count=result.metadata.matched_count,
                        truncated=result.metadata.truncated or result.metadata.partial,
                    )
                )
            dependencies = await self._repository.get_service_dependencies(
                service, start, end, limit=20
            )
            for edge in dependencies.items:
                candidates.append(
                    EvidenceCandidate(
                        evidence_type="dependency_edge",
                        source=QueryLocator(
                            query_id=deterministic_id("query", [edge.edge_id]),
                            index_alias=self._trace_alias,
                        ),
                        service=incident.primary_service,
                        window=window,
                        summary=(
                            f"Observed dependency {edge.source_service.name} to "
                            f"{edge.target_service.name}"
                        ),
                        snapshot=DependencySnapshot(edge=edge),
                        template_id="dependencies-by-service",
                        index_alias=self._trace_alias,
                        matched_count=dependencies.metadata.matched_count,
                        truncated=(
                            dependencies.metadata.truncated or dependencies.metadata.partial
                        ),
                    )
                )
        except TelemetryRepositoryError:
            return candidates
        return candidates


def _instant_end(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed + timedelta(microseconds=1)).isoformat().replace("+00:00", "Z")


def anomaly_candidate(anomaly: NormalizedAnomaly) -> EvidenceCandidate:
    if anomaly.affected_window is None:
        raise ValueError("anomalous evidence requires an affected window")
    return EvidenceCandidate(
        evidence_type="anomaly_result",
        source=DocumentLocator(
            index=anomaly.source.index,
            document_id=anomaly.source.document_id,
        ),
        service=anomaly.service,
        window=anomaly.affected_window,
        summary=(
            f"Normalized {anomaly.feature} anomaly grade {anomaly.anomaly_grade:.6f}"
            if anomaly.anomaly_grade is not None
            else f"Normalized {anomaly.feature} anomaly"
        ),
        snapshot=AnomalySnapshot(anomaly=anomaly),
        template_id="anomaly-by-id",
        index_alias="aiops-anomalies-v1",
    )


def bucket_candidate(bucket: ServiceMetricBucket) -> EvidenceCandidate:
    return EvidenceCandidate(
        evidence_type="metric_bucket",
        source=DocumentLocator(index="aiops-service-metrics-v1", document_id=bucket.bucket_id),
        service=bucket.service,
        window=bucket.window,
        summary=(
            f"Finalized metric bucket: requests={bucket.request_count}, "
            f"error_rate={bucket.error_rate}, latency_p95_ms={bucket.latency_p95_ms}"
        ),
        snapshot=MetricBucketSnapshot(bucket=bucket),
        template_id="metric-bucket-by-id",
        index_alias="aiops-service-metrics-v1",
    )


def make_evidence_item(
    incident_id: str,
    candidate: EvidenceCandidate,
    *,
    created_at: str,
) -> EvidenceItem:
    snapshot = candidate.snapshot.model_dump(mode="json")
    content_sha256 = _hash(snapshot)
    source = candidate.source.model_dump(mode="json")
    evidence_id = deterministic_id(
        "ev",
        [candidate.evidence_type, _canonical(source).decode(), content_sha256, REDACTION_VERSION],
    )
    query_id = deterministic_id(
        "query",
        [
            candidate.template_id,
            candidate.service.service_id,
            candidate.window.start,
            candidate.window.end,
            candidate.source.model_dump_json(),
        ],
    )
    parameters = QueryParameters(
        service_ids=[candidate.service.service_id],
        window=candidate.window,
        features=[],
        incident_id=incident_id,
        document_id=(
            candidate.source.document_id if isinstance(candidate.source, DocumentLocator) else None
        ),
        limit=1,
        include_native=False,
    )
    summary = SECRET_PATTERN.sub(r"\1=[REDACTED]", candidate.summary)[:512]
    item = EvidenceItem(
        owner_incident_id=incident_id,
        evidence_id=evidence_id,
        evidence_type=candidate.evidence_type,  # type: ignore[arg-type]
        source=candidate.source,
        service=candidate.service,
        window=candidate.window,
        summary=summary,
        quality_status="partial" if candidate.truncated else "complete",
        quality_reasons=["truncated"] if candidate.truncated else [],
        redaction_status=("redacted" if summary != candidate.summary else "checked_clear"),
        redaction_version=REDACTION_VERSION,
        provenance=Provenance(
            query_id=query_id,
            template_id=candidate.template_id,
            template_version="1.0.0",
            parameters=parameters,
            retrieved_at=created_at,
            source_cutoff=created_at,
            returned_count=1,
            matched_count=candidate.matched_count,
            truncated=candidate.truncated,
        ),
        snapshot=candidate.snapshot,
        content_sha256=content_sha256,
        stored_bytes=1,
        created_at=created_at,
    )
    for _ in range(8):
        encoded = len(_canonical(item.model_dump(mode="json")))
        updated = item.model_copy(update={"stored_bytes": encoded})
        if updated.stored_bytes == item.stored_bytes:
            break
        item = updated
    if item.stored_bytes > ITEM_LIMIT:
        raise ValueError("evidence item exceeds byte limit")
    return item


def build_bundle(
    incident_id: str,
    version: int,
    window: TimeRange,
    candidates: list[EvidenceCandidate],
    *,
    now: datetime,
    max_items: int = ITEM_COUNT_LIMIT,
    max_bytes: int = BUNDLE_LIMIT,
) -> tuple[list[EvidenceItem], EvidenceBundle]:
    created_at = _utc(now)
    selected: list[EvidenceItem] = []
    total = 0
    truncated = False
    for candidate in candidates:
        item = make_evidence_item(incident_id, candidate, created_at=created_at)
        if len(selected) >= min(max_items, ITEM_COUNT_LIMIT) or total + item.stored_bytes > min(
            max_bytes, BUNDLE_LIMIT
        ):
            truncated = True
            break
        if item.evidence_id not in {existing.evidence_id for existing in selected}:
            selected.append(item)
            total += item.stored_bytes
    if not selected:
        raise ValueError("an evidence bundle requires at least one bounded item")
    evidence_ids = [item.evidence_id for item in selected]
    bundle_id = deterministic_id("bundle", [incident_id, version, _hash(evidence_ids)])
    reasons: list[ReasonCode] = ["truncated"] if truncated else []
    bundle = EvidenceBundle(
        owner_incident_id=incident_id,
        bundle_id=bundle_id,
        incident_id=incident_id,
        version=version,
        window=window,
        evidence_ids=evidence_ids,
        quality_status="partial" if truncated else "complete",
        quality_reasons=reasons,
        total_bytes=total,
        created_at=created_at,
    )
    return selected, bundle
