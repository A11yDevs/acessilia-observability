"""Edit this file to point the kit at one AgentOS project.

Credentials belong in .env, not here. Run `python -m agno_observability_kit.configure` after edits.
"""

import os

from agno_observability_kit.settings import ProjectConfig


CONFIG = ProjectConfig(
    project_id="acessilia",
    project_name="Acessília · Central de observabilidade",
    environment=os.getenv("OBS_ENVIRONMENT", "develop"),
    acessilia_url=os.getenv("ACESSILIA_API_URL", ""),  # Base URL, without /api/v1.
    toolbox_url=os.getenv("TOOLBOX_API_URL", ""),  # Base URL, without /v1.
    agentos_url=os.getenv("AGENTOS_URL", ""),  # Optional showcase, separate from jobs.
    telemetry_db=os.getenv("OBS_DB_PATH", "var/observability.sqlite3"),
    retention_days=int(os.getenv("OBS_RETENTION_DAYS", "7")),
    max_events=int(os.getenv("OBS_MAX_EVENTS", "100000")),
    enable_test_console=os.getenv("OBS_ENABLE_TEST_CONSOLE", "false").lower() == "true",
    observability_bind_ip="127.0.0.1",  # Use a private network address for remote ingestion.
    observability_ingest_url="http://host.docker.internal",  # Address reachable from the application collector.
    collector_bind_ip="127.0.0.1",  # Change only if another container must reach collector OTLP.
    metrics_target="",  # Optional host:port exposing Prometheus metrics near the collector.
    metrics_path="/metrics",
    collector_log_dir="",  # Optional absolute directory on the monitored host.
    collector_log_glob="*.log",
    langfuse_otlp_url="",  # Optional: https://host/api/public/otel
    langfuse_ui_url="",  # Optional browser link, such as https://host
    langfuse_bind_ip="127.0.0.1",
    langfuse_ui_port=3001,
    langfuse_media_port=9092,
    langfuse_media_url="http://localhost:9092",
    grafana_ui_url="http://localhost:3000",  # Browser URL; use a tunnel for remote viewing.
    metric_queries={},  # Optional named PromQL queries for this project.
)
