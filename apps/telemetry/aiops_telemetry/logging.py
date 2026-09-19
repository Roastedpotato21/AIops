import json
import logging
from datetime import UTC, datetime
from typing import TextIO

from opentelemetry import trace


class JsonTelemetryFormatter(logging.Formatter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self._service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        context = trace.get_current_span().get_span_context()
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "severity": record.levelname,
            "service": self._service_name,
            "event": getattr(record, "event", record.getMessage()),
            "message": record.getMessage(),
            "trace_id": f"{context.trace_id:032x}" if context.is_valid else "",
            "span_id": f"{context.span_id:016x}" if context.is_valid else "",
        }
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def console_handler(service_name: str, stream: TextIO | None = None) -> logging.Handler:
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonTelemetryFormatter(service_name))
    return handler
