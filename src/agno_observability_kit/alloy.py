"""Render the application collector configuration."""

from __future__ import annotations

import json

from agno_observability_kit.settings import ProjectConfig


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_alloy(config: ProjectConfig) -> str:
    server = config.observability_ingest_url.rstrip("/")
    trace_destinations = ["otelcol.exporter.otlphttp.tempo.input"]
    if config.langfuse_otlp_url:
        trace_destinations.append("otelcol.exporter.otlphttp.langfuse.input")
    blocks = [
        'otelcol.receiver.otlp "application" {\n'
        '  grpc { endpoint = "0.0.0.0:4317" }\n'
        '  http { endpoint = "0.0.0.0:4318" }\n'
        '  output {\n'
        '    metrics = [otelcol.exporter.prometheus.server.input]\n'
        '    logs = [otelcol.exporter.loki.server.input]\n'
        f'    traces = [{", ".join(trace_destinations)}]\n'
        '  }\n'
        '}\n',
        'otelcol.exporter.prometheus "server" {\n'
        '  forward_to = [prometheus.remote_write.server.receiver]\n'
        '}\n',
        'prometheus.remote_write "server" {\n'
        f'  external_labels = {{ project_id = {_quoted(config.project_id)}, environment = {_quoted(config.environment)} }}\n'
        f'  endpoint {{ url = {_quoted(f"{server}:9090/api/v1/write")} }}\n'
        '}\n',
        'prometheus.exporter.self "collector" {}\n',
        'prometheus.scrape "collector" {\n'
        '  targets = prometheus.exporter.self.collector.targets\n'
        '  scrape_interval = "15s"\n'
        '  forward_to = [prometheus.remote_write.server.receiver]\n'
        '}\n',
        'otelcol.exporter.loki "server" {\n'
        '  forward_to = [loki.write.server.receiver]\n'
        '}\n',
        'loki.write "server" {\n'
        f'  external_labels = {{ project_id = {_quoted(config.project_id)}, environment = {_quoted(config.environment)} }}\n'
        f'  endpoint {{ url = {_quoted(f"{server}:3100/loki/api/v1/push")} }}\n'
        '}\n',
        'otelcol.exporter.otlphttp "tempo" {\n'
        f'  client {{ endpoint = {_quoted(f"{server}:4318")} }}\n'
        '}\n',
    ]
    if config.langfuse_otlp_url:
        blocks.extend([
            'otelcol.auth.basic "langfuse" {\n'
            '  username = sys.env("LANGFUSE_PUBLIC_KEY")\n'
            '  password = sys.env("LANGFUSE_SECRET_KEY")\n'
            '}\n',
            'otelcol.exporter.otlphttp "langfuse" {\n'
            '  client {\n'
            f'    endpoint = {_quoted(config.langfuse_otlp_url.rstrip("/"))}\n'
            '    auth = otelcol.auth.basic.langfuse.handler\n'
            '    headers = { "x-langfuse-ingestion-version" = "4" }\n'
            '  }\n'
            '}\n',
        ])
    if config.metrics_target:
        blocks.extend([
            'prometheus.scrape "application" {\n'
            '  targets = [{\n'
            f'    __address__ = {_quoted(config.metrics_target)},\n'
            f'    __metrics_path__ = {_quoted(config.metrics_path)},\n'
            f'    project_id = {_quoted(config.project_id)},\n'
            f'    environment = {_quoted(config.environment)},\n'
            '  }]\n'
            '  forward_to = [prometheus.remote_write.server.receiver]\n'
            '}\n',
        ])
    if config.collector_log_dir:
        blocks.extend([
            'loki.source.file "application" {\n'
            '  targets = [{\n'
            f'    __path__ = {_quoted(f"/var/log/observed/{config.collector_log_glob}")},\n'
            f'    project_id = {_quoted(config.project_id)},\n'
            f'    environment = {_quoted(config.environment)},\n'
            '    job = "application",\n'
            '  }]\n'
            '  file_match { enabled = true }\n'
            '  forward_to = [loki.write.server.receiver]\n'
            '}\n',
        ])
    return "\n".join(blocks)
