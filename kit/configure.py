"""Generate local Compose and Alloy settings from config.py."""

from __future__ import annotations

import json
from pathlib import Path

from config import CONFIG
from kit.settings import ProjectConfig


ROOT = Path(__file__).resolve().parents[1]


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_alloy(config: ProjectConfig) -> str:
    hub = config.hub_ingest_url.rstrip("/")
    trace_destinations = ["otelcol.exporter.otlphttp.tempo.input"]
    if config.langfuse_otlp_url:
        trace_destinations.append("otelcol.exporter.otlphttp.langfuse.input")
    blocks = [
        'otelcol.receiver.otlp "application" {\n'
        '  grpc { endpoint = "0.0.0.0:4317" }\n'
        '  http { endpoint = "0.0.0.0:4318" }\n'
        '  output {\n'
        '    metrics = [otelcol.exporter.prometheus.hub.input]\n'
        '    logs = [otelcol.exporter.loki.hub.input]\n'
        f'    traces = [{", ".join(trace_destinations)}]\n'
        '  }\n'
        '}\n',
        'otelcol.exporter.prometheus "hub" {\n'
        '  forward_to = [prometheus.remote_write.hub.receiver]\n'
        '}\n',
        'prometheus.remote_write "hub" {\n'
        f'  external_labels = {{ project_id = {_quoted(config.project_id)}, environment = {_quoted(config.environment)} }}\n'
        f'  endpoint {{ url = {_quoted(f"{hub}:9090/api/v1/write")} }}\n'
        '}\n',
        'otelcol.exporter.loki "hub" {\n'
        '  forward_to = [loki.write.hub.receiver]\n'
        '}\n',
        'loki.write "hub" {\n'
        f'  external_labels = {{ project_id = {_quoted(config.project_id)}, environment = {_quoted(config.environment)} }}\n'
        f'  endpoint {{ url = {_quoted(f"{hub}:3100/loki/api/v1/push")} }}\n'
        '}\n',
        'otelcol.exporter.otlphttp "tempo" {\n'
        f'  client {{ endpoint = {_quoted(f"{hub}:4318")} }}\n'
        '}\n',
    ]
    if config.langfuse_otlp_url:
        blocks.extend([
            'otelcol.auth.basic "langfuse" {\n'
            '  client_auth {\n'
            '    username = sys.env("LANGFUSE_PUBLIC_KEY")\n'
            '    password = sys.env("LANGFUSE_SECRET_KEY")\n'
            '  }\n'
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
            '  forward_to = [prometheus.remote_write.hub.receiver]\n'
            '}\n',
        ])
    if config.edge_log_dir:
        blocks.extend([
            'loki.source.file "application" {\n'
            '  targets = [{\n'
            f'    __path__ = {_quoted(f"/var/log/observed/{config.edge_log_glob}")},\n'
            f'    project_id = {_quoted(config.project_id)},\n'
            f'    environment = {_quoted(config.environment)},\n'
            '    job = "application",\n'
            '  }]\n'
            '  file_match { enabled = true }\n'
            '  forward_to = [loki.write.hub.receiver]\n'
            '}\n',
        ])
    return "\n".join(blocks)


def write_config(config: ProjectConfig = CONFIG, root: Path = ROOT) -> None:
    edge = root / "edge"
    edge.mkdir(exist_ok=True)
    loadtest = root / "loadtest"
    loadtest.mkdir(exist_ok=True)
    log_dir = Path(config.edge_log_dir) if config.edge_log_dir else edge / "logs"
    if not config.edge_log_dir:
        log_dir.mkdir(exist_ok=True)
    (root / ".runtime.env").write_text(
        f"HUB_BIND_IP={config.hub_bind_ip}\n"
        f"LANGFUSE_BIND_IP={config.langfuse_bind_ip}\n"
        f"LANGFUSE_UI_PORT={config.langfuse_ui_port}\n"
        f"LANGFUSE_MEDIA_PORT={config.langfuse_media_port}\n"
        f"LANGFUSE_UI_URL={_quoted(config.langfuse_ui_url or f'http://localhost:{config.langfuse_ui_port}')}\n"
        f"LANGFUSE_MEDIA_URL={_quoted(config.langfuse_media_url)}\n"
    )
    (edge / ".runtime.env").write_text(
        f"EDGE_LOG_DIR={_quoted(str(log_dir))}\nEDGE_BIND_IP={config.edge_bind_ip}\n"
    )
    (edge / "generated.alloy").write_text(render_alloy(config))
    (loadtest / ".runtime.env").write_text(f"LOCUST_TARGET_URL={_quoted(config.agentos_url)}\n")


if __name__ == "__main__":
    write_config()
    print("Wrote runtime settings for hub, edge and loadtest")
