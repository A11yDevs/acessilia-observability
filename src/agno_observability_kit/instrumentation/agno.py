"""Send Agno traces and application telemetry to a nearby OTLP collector."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass
class AgnoTelemetry:
    tracer_provider: Any
    meter_provider: Any
    logger_provider: Any
    run_counter: Any
    run_duration: Any

    def record_run(self, *, component_type: str, status: str, duration_seconds: float) -> None:
        if component_type not in {"agent", "team", "workflow"}:
            raise ValueError("component_type must be agent, team or workflow")
        if status not in {"ok", "error"} or not math.isfinite(duration_seconds) or duration_seconds < 0:
            raise ValueError("status must be ok or error and duration_seconds must be non-negative")
        attributes = {"component_type": component_type, "status": status}
        self.run_counter.add(1, attributes)
        self.run_duration.record(duration_seconds, attributes)

    def flush(self) -> bool:
        results = (
            self.tracer_provider.force_flush(),
            self.meter_provider.force_flush(),
            self.logger_provider.force_flush(),
        )
        return all(results)


def configure_agno_telemetry(
    *,
    service_name: str,
    project_id: str,
    environment: str,
    collector_url: str = "http://127.0.0.1:4318",
    loggers: tuple[str, ...] = (),
) -> AgnoTelemetry:
    """Configure once at application startup, before creating AgentOS or running agents."""
    if not service_name.strip() or not project_id.strip() or not environment.strip():
        raise ValueError("service_name, project_id and environment are required")
    parsed = urlparse(collector_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("collector_url must be an HTTP(S) base URL without a path or credentials")

    try:
        from openinference.instrumentation.agno import AgnoInstrumentor
        from opentelemetry import metrics, trace
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace import SpanProcessor
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.trace import ProxyTracerProvider, StatusCode
    except ImportError as exc:
        raise RuntimeError("Install the optional telemetry dependencies with: pip install 'agno-observability-kit[telemetry]'") from exc

    if not isinstance(trace.get_tracer_provider(), ProxyTracerProvider):
        raise RuntimeError("A tracer provider already exists. Configure its OTLP exporter and AgnoInstrumentor directly instead.")

    resource = Resource.create({"service.name": service_name, "project_id": project_id, "environment": environment})
    endpoint = collector_url.rstrip("/")

    metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"))
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    meter = meter_provider.get_meter("agno_observability_kit")
    run_counter = meter.create_counter("agno_runs", description="Completed agent, team and workflow runs")
    run_duration = meter.create_histogram("agno_run_duration_seconds", unit="s", description="Agent, team and workflow run duration")

    class RunMetricSpanProcessor(SpanProcessor):
        def on_end(self, span: Any) -> None:
            if span.instrumentation_scope.name != "openinference.instrumentation.agno":
                return
            attributes = span.attributes or {}
            kind = attributes.get("openinference.span.kind")
            if kind == "AGENT":
                component_type = "team" if "agno.team" in attributes else "agent"
            elif kind == "CHAIN" and span.name.rsplit(".", 1)[-1] in {
                "run", "arun", "run_stream", "arun_stream", "continue_run", "acontinue_run"
            }:
                component_type = "workflow"
            else:
                return
            if span.status.status_code not in {StatusCode.OK, StatusCode.ERROR}:
                return
            if span.start_time is None or span.end_time is None or span.end_time < span.start_time:
                return
            labels = {"component_type": component_type, "status": "error" if span.status.status_code == StatusCode.ERROR else "ok"}
            run_counter.add(1, labels)
            run_duration.record((span.end_time - span.start_time) / 1_000_000_000, labels)

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(RunMetricSpanProcessor())
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")))
    AgnoInstrumentor().instrument(tracer_provider=tracer_provider)
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs")))
    set_logger_provider(logger_provider)
    for name in loggers:
        logging.getLogger(name).addHandler(LoggingHandler(logger_provider=logger_provider))

    return AgnoTelemetry(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
        run_counter=run_counter,
        run_duration=run_duration,
    )
