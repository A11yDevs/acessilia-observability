"""Edit this file to point the kit at one AgentOS project.

Credentials belong in .env, not here. Run `python -m agno_observability_kit.configure` after edits.
"""

from agno_observability_kit.settings import ProjectConfig


CONFIG = ProjectConfig(
    project_id="example",
    project_name="Example project",
    environment="local",
    agentos_url="",  # Example: http://100.64.0.10:7777
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
