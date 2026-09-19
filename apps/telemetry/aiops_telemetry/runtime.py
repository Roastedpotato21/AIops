import logging
import socket
import time
from dataclasses import dataclass
from typing import TextIO

import httpx
from fastapi import FastAPI, Request
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.metrics import Meter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import (
    BatchLogRecordProcessor,
    LogRecordExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.semconv.attributes.deployment_attributes import (
    DEPLOYMENT_ENVIRONMENT_NAME,
)

from aiops_telemetry.config import TelemetrySettings
from aiops_telemetry.logging import console_handler

REQUESTS_METRIC = "demo.http.server.requests"
ERRORS_METRIC = "demo.http.server.errors"
DURATION_METRIC = "demo.http.server.duration"
DURATION_UNIT = "ms"


def build_resource(settings: TelemetrySettings) -> Resource:
    return Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.namespace": settings.otel_service_namespace,
            "service.version": settings.service_version,
            "service.instance.id": settings.service_instance_id or socket.gethostname(),
            DEPLOYMENT_ENVIRONMENT_NAME: settings.deployment_environment,
        }
    )


@dataclass
class TelemetryRuntime:
    settings: TelemetrySettings
    logger: logging.Logger
    tracer_provider: TracerProvider | None = None
    meter_provider: MeterProvider | None = None
    logger_provider: LoggerProvider | None = None
    meter: Meter | None = None

    def instrument_httpx_client(self, client: httpx.AsyncClient) -> None:
        if self.tracer_provider is None:
            return
        HTTPXClientInstrumentor().instrument_client(
            client,
            tracer_provider=self.tracer_provider,
            meter_provider=self.meter_provider,
        )

    def shutdown(self) -> None:
        for provider in (self.logger_provider, self.meter_provider, self.tracer_provider):
            if provider is not None:
                provider.shutdown()


def _configure_logger(
    settings: TelemetrySettings,
    logger_provider: LoggerProvider | None,
    stream: TextIO | None,
) -> logging.Logger:
    logger = logging.getLogger(f"aiops.demo.{settings.otel_service_name}")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(settings.log_level)
    logger.addHandler(console_handler(settings.otel_service_name, stream))
    if logger_provider is not None:
        logger.addHandler(LoggingHandler(logger_provider=logger_provider))
    return logger


def configure_telemetry(
    settings: TelemetrySettings,
    *,
    span_exporter: SpanExporter | None = None,
    metric_reader: MetricReader | None = None,
    log_exporter: LogRecordExporter | None = None,
    log_stream: TextIO | None = None,
) -> TelemetryRuntime:
    if not settings.telemetry_enabled:
        return TelemetryRuntime(
            settings=settings,
            logger=_configure_logger(settings, None, log_stream),
        )

    resource = build_resource(settings)
    tracer_provider = TracerProvider(resource=resource)
    if span_exporter is None:
        trace_exporter = OTLPSpanExporter(
            endpoint=settings.otel_exporter_otlp_endpoint,
            insecure=settings.otel_exporter_otlp_insecure,
        )
        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                trace_exporter,
                max_queue_size=settings.otel_batch_max_queue_size,
                max_export_batch_size=settings.otel_batch_max_export_batch_size,
                schedule_delay_millis=settings.otel_batch_schedule_delay_millis,
            )
        )
    else:
        tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    if metric_reader is None:
        metric_exporter = OTLPMetricExporter(
            endpoint=settings.otel_exporter_otlp_endpoint,
            insecure=settings.otel_exporter_otlp_insecure,
        )
        metric_reader = PeriodicExportingMetricReader(
            metric_exporter,
            export_interval_millis=settings.otel_metric_export_interval_millis,
        )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])

    logger_provider = LoggerProvider(resource=resource)
    if log_exporter is None:
        otlp_log_exporter = OTLPLogExporter(
            endpoint=settings.otel_exporter_otlp_endpoint,
            insecure=settings.otel_exporter_otlp_insecure,
        )
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(
                otlp_log_exporter,
                max_queue_size=settings.otel_batch_max_queue_size,
                max_export_batch_size=settings.otel_batch_max_export_batch_size,
                schedule_delay_millis=settings.otel_batch_schedule_delay_millis,
            )
        )
    else:
        logger_provider.add_log_record_processor(SimpleLogRecordProcessor(log_exporter))

    meter = meter_provider.get_meter("aiops.demo.http", settings.service_version)
    runtime = TelemetryRuntime(
        settings=settings,
        logger=_configure_logger(settings, logger_provider, log_stream),
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
        meter=meter,
    )
    return runtime


def instrument_fastapi(
    app: FastAPI,
    runtime: TelemetryRuntime,
    business_routes: set[str],
) -> None:
    if runtime.tracer_provider is None or runtime.meter_provider is None or runtime.meter is None:
        return
    request_counter = runtime.meter.create_counter(
        REQUESTS_METRIC, unit="{request}", description="Completed demo server requests"
    )
    error_counter = runtime.meter.create_counter(
        ERRORS_METRIC, unit="{request}", description="Completed demo server requests with 5xx"
    )
    duration = runtime.meter.create_histogram(
        DURATION_METRIC, unit=DURATION_UNIT, description="Demo server request duration"
    )

    @app.middleware("http")
    async def record_server_metrics(request: Request, call_next):  # type: ignore[no-untyped-def]
        route = request.url.path
        if route not in business_routes:
            return await call_next(request)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            attributes = {
                "http.request.method": request.method,
                "http.route": route,
                "http.response.status_code": status_code,
            }
            request_counter.add(1, attributes)
            if status_code >= 500:
                error_counter.add(1, attributes)
            duration.record((time.perf_counter() - started) * 1_000, attributes)

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=runtime.tracer_provider,
        meter_provider=runtime.meter_provider,
        excluded_urls="/health,/docs,/openapi.json,/__faults",
    )
