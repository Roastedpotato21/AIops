import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from app.models.telemetry import (
    DependencyEdge,
    NativeHistogram,
    NativeMetric,
    ServiceReference,
    SourceDocument,
    TelemetryLog,
    TelemetryService,
    TelemetrySpan,
    utc_timestamp_to_ns,
)

ALLOWED_METRIC_LABELS = {
    "http.request.method",
    "http.route",
    "http.response.status_code",
}


class MalformedTelemetryDocument(ValueError):
    pass


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _service_id(namespace: str, environment: str, name: str) -> str:
    encoded = json.dumps(
        [namespace, environment, name],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode()
    return f"svc_{hashlib.sha256(encoded).hexdigest()}"


def dependency_edge_id(
    source: ServiceReference,
    target: ServiceReference,
    start_time: str,
    end_time: str,
) -> str:
    encoded = json.dumps(
        [
            _service_id(source.namespace, source.environment, source.name),
            _service_id(target.namespace, target.environment, target.name),
            start_time,
            end_time,
            "1.0.0",
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode()
    return f"edge_{hashlib.sha256(encoded).hexdigest()}"


def _source(hit: Mapping[str, Any]) -> tuple[SourceDocument, Mapping[str, Any]]:
    try:
        locator = SourceDocument(
            index=str(hit["_index"]),
            document_id=str(hit["_id"]),
        )
        document = hit["_source"]
    except (KeyError, TypeError, ValidationError) as exc:
        raise MalformedTelemetryDocument("telemetry hit is missing source identity") from exc
    if not isinstance(document, Mapping):
        raise MalformedTelemetryDocument("telemetry source must be an object")
    return locator, document


def _service(document: Mapping[str, Any]) -> TelemetryService:
    resource = document.get("resource")
    if not isinstance(resource, Mapping):
        raise MalformedTelemetryDocument("telemetry resource is missing")
    attributes = resource.get("attributes")
    if not isinstance(attributes, Mapping):
        raise MalformedTelemetryDocument("telemetry resource attributes are missing")
    namespace = attributes.get("service.namespace")
    name = attributes.get("service.name") or document.get("serviceName")
    instance_id = attributes.get("service.instance.id")
    current_environment = attributes.get("deployment.environment.name")
    legacy_environment = attributes.get("deployment.environment")
    if (
        current_environment is not None
        and legacy_environment is not None
        and current_environment != legacy_environment
    ):
        raise MalformedTelemetryDocument("deployment environment attributes conflict")
    environment = current_environment or legacy_environment
    if not all(isinstance(value, str) and value for value in (namespace, name, environment)):
        raise MalformedTelemetryDocument("telemetry service identity is incomplete")
    if not isinstance(instance_id, str) or not instance_id:
        raise MalformedTelemetryDocument("telemetry service instance identity is missing")
    version = attributes.get("service.version")
    if version is not None and not isinstance(version, str):
        raise MalformedTelemetryDocument("telemetry service version is invalid")
    try:
        return TelemetryService(
            service_id=_service_id(namespace, environment, name),
            namespace=namespace,
            environment=environment,
            name=name,
            instance_id=instance_id,
            version=version,
        )
    except ValidationError as exc:
        raise MalformedTelemetryDocument("telemetry service identity is invalid") from exc


def _optional_hex(value: object) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise MalformedTelemetryDocument("telemetry identifier is invalid")
    return value.lower()


def _status(attributes: Mapping[str, Any], document: Mapping[str, Any]) -> int | None:
    current = attributes.get("http.response.status_code")
    legacy = attributes.get("http.status_code")
    if current is not None and legacy is not None and current != legacy:
        raise MalformedTelemetryDocument("HTTP status attributes conflict")
    value = current if current is not None else legacy
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise MalformedTelemetryDocument("HTTP status must be an integer")
    return value


def map_log_document(hit: Mapping[str, Any]) -> TelemetryLog:
    locator, document = _source(hit)
    body = document.get("body")
    if not isinstance(body, str):
        raise MalformedTelemetryDocument("log body must be text")
    severity = document.get("severityText")
    if isinstance(severity, str):
        severity = severity.upper()
        severity = "WARN" if severity == "WARNING" else severity
    else:
        number = document.get("severityNumber")
        if isinstance(number, bool) or not isinstance(number, int):
            raise MalformedTelemetryDocument("log severity is missing")
        severity = (
            "DEBUG"
            if number <= 8
            else "INFO"
            if number <= 12
            else "WARN"
            if number <= 16
            else "ERROR"
            if number <= 20
            else "FATAL"
        )
    attributes = document.get("attributes")
    attributes = attributes if isinstance(attributes, Mapping) else {}
    try:
        return TelemetryLog(
            source=locator,
            service=_service(document),
            event_time=document["time"],
            observed_time=document.get("observedTimestamp"),
            severity=severity,
            body=body,
            trace_id=_optional_hex(document.get("traceId")),
            span_id=_optional_hex(document.get("spanId")),
            event=attributes.get("event") if isinstance(attributes.get("event"), str) else None,
            error_type=(
                attributes.get("exception.type")
                if isinstance(attributes.get("exception.type"), str)
                else None
            ),
        )
    except (KeyError, ValidationError, ValueError) as exc:
        raise MalformedTelemetryDocument("log document is invalid") from exc


def map_span_document(hit: Mapping[str, Any]) -> TelemetrySpan:
    locator, document = _source(hit)
    attributes = document.get("attributes")
    attributes = attributes if isinstance(attributes, Mapping) else {}
    status_object = document.get("status")
    status_object = status_object if isinstance(status_object, Mapping) else {}
    status_code = status_object.get("code", 0)
    status = {0: "UNSET", 1: "OK", 2: "ERROR"}.get(status_code)
    if status is None:
        raise MalformedTelemetryDocument("span status code is unsupported")
    kind = document.get("kind")
    if not isinstance(kind, str):
        raise MalformedTelemetryDocument("span kind is missing")
    kind = kind.removeprefix("SPAN_KIND_")
    duration_ns = document.get("durationInNanos")
    if isinstance(duration_ns, bool) or not isinstance(duration_ns, int):
        raise MalformedTelemetryDocument("span duration is invalid")
    immutable = {
        "service": _service(document).model_dump(),
        "trace_id": document.get("traceId"),
        "span_id": document.get("spanId"),
        "parent_span_id": document.get("parentSpanId"),
        "name": document.get("name"),
        "kind": kind,
        "start_time": document.get("startTime"),
        "end_time": document.get("endTime"),
        "duration_ns": duration_ns,
        "status": status,
        "http_status_code": _status(attributes, document),
        "http_route": attributes.get("http.route"),
    }
    try:
        return TelemetrySpan(
            source=locator,
            service=TelemetryService.model_validate(immutable["service"]),
            trace_id=str(document["traceId"]).lower(),
            span_id=str(document["spanId"]).lower(),
            parent_span_id=_optional_hex(document.get("parentSpanId")),
            name=document["name"],
            kind=kind,
            start_time=document["startTime"],
            end_time=document["endTime"],
            duration_ns=duration_ns,
            duration_ms=duration_ns / 1_000_000,
            status=status,
            http_method=attributes.get("http.request.method")
            or attributes.get("http.method"),
            http_route=attributes.get("http.route"),
            http_status_code=immutable["http_status_code"],
            content_sha256=_canonical_hash(immutable),
        )
    except (KeyError, ValidationError, ValueError, TypeError) as exc:
        raise MalformedTelemetryDocument("span document is invalid") from exc


def _finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MalformedTelemetryDocument(f"{field_name} must be numeric")
    converted = float(value)
    if not math.isfinite(converted):
        raise MalformedTelemetryDocument(f"{field_name} must be finite")
    return converted


def map_metric_document(hit: Mapping[str, Any]) -> NativeMetric:
    locator, document = _source(hit)
    raw_kind = document.get("kind")
    metric_type = {
        "GAUGE": "gauge",
        "SUM": "sum",
        "HISTOGRAM": "histogram",
    }.get(raw_kind)
    if metric_type is None:
        raise MalformedTelemetryDocument("metric kind is unsupported")
    raw_temporality = document.get("aggregationTemporality", "")
    temporality = {
        "AGGREGATION_TEMPORALITY_DELTA": "delta",
        "AGGREGATION_TEMPORALITY_CUMULATIVE": "cumulative",
        "": "unspecified",
    }.get(raw_temporality)
    if temporality is None:
        raise MalformedTelemetryDocument("metric temporality is unsupported")
    attributes = document.get("attributes")
    attributes = attributes if isinstance(attributes, Mapping) else {}
    labels = {
        key: str(value)
        for key, value in attributes.items()
        if key in ALLOWED_METRIC_LABELS
        and isinstance(value, (str, int, float))
        and not isinstance(value, bool)
    }
    histogram = None
    value = None
    if metric_type == "histogram":
        bounds = document.get("explicitBounds")
        counts = document.get("bucketCountsList")
        if not isinstance(bounds, list) or not isinstance(counts, list):
            raise MalformedTelemetryDocument("histogram layout is unsupported")
        histogram = NativeHistogram(
            count=document.get("count"),
            sum=(
                _finite_number(document["sum"], "histogram sum")
                if document.get("sum") is not None
                else None
            ),
            minimum=(
                _finite_number(document["min"], "histogram minimum")
                if document.get("min") is not None
                else None
            ),
            maximum=(
                _finite_number(document["max"], "histogram maximum")
                if document.get("max") is not None
                else None
            ),
            bounds=[_finite_number(item, "histogram bound") for item in bounds],
            counts=[
                item
                for item in counts
                if isinstance(item, int) and not isinstance(item, bool) and item >= 0
            ],
        )
        if len(histogram.counts) != len(counts):
            raise MalformedTelemetryDocument("histogram counts are invalid")
    else:
        value = _finite_number(document.get("value"), "metric value")
    try:
        return NativeMetric(
            source=locator,
            service=_service(document),
            name=document["name"],
            description=str(document.get("description", "")),
            unit=str(document.get("unit", "")),
            metric_type=metric_type,
            temporality=temporality,
            monotonic=document.get("isMonotonic") if metric_type == "sum" else None,
            start_time=document.get("startTime"),
            event_time=document["time"],
            value=value,
            histogram=histogram,
            labels=labels,
        )
    except (KeyError, ValidationError, ValueError, TypeError) as exc:
        raise MalformedTelemetryDocument("metric document is invalid") from exc


def map_native_dependency_document(
    hit: Mapping[str, Any],
    *,
    services: Mapping[str, ServiceReference],
    window_start: str,
    window_end: str,
    observed_at: str,
) -> DependencyEdge:
    _, document = _source(hit)
    destination = document.get("destination")
    if document.get("kind") != "SPAN_KIND_CLIENT" or not isinstance(destination, Mapping):
        raise MalformedTelemetryDocument("service-map document is not a client edge")
    source_name = document.get("serviceName")
    target_name = destination.get("domain")
    if source_name not in services or target_name not in services:
        raise MalformedTelemetryDocument("service-map edge is outside registered scope")
    source_service = services[source_name]
    target_service = services[target_name]
    try:
        return DependencyEdge(
            edge_id=dependency_edge_id(
                source_service,
                target_service,
                window_start,
                window_end,
            ),
            source_service=source_service,
            target_service=target_service,
            window_start=window_start,
            window_end=window_end,
            observed_trace_count=None,
            sample_trace_ids=[],
            observed_at=observed_at,
            source_kind="native_service_map",
        )
    except ValidationError as exc:
        raise MalformedTelemetryDocument("service-map edge is invalid") from exc


def span_completion_ns(span: TelemetrySpan) -> int:
    return utc_timestamp_to_ns(span.end_time)
