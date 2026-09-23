"""Edit this file to point the kit at one AgentOS project.

Credentials belong in .env, not here. Run `python -m kit.configure` after edits.
"""

from kit.settings import ProjectConfig


CONFIG = ProjectConfig(
    project_id="example",
    project_name="Example project",
    environment="local",
    agentos_url="",  # Example: http://100.64.0.10:7777
    hub_bind_ip="127.0.0.1",  # Use a private network address for remote ingestion.
    hub_ingest_url="http://host.docker.internal",  # Address reachable from edge Alloy.
    edge_bind_ip="127.0.0.1",  # Change only if another container must reach edge OTLP.
    metrics_target="",  # Optional host:port exposing Prometheus metrics near edge Alloy.
    metrics_path="/metrics",
    edge_log_dir="",  # Optional absolute directory on the monitored host.
    edge_log_glob="*.log",
    langfuse_otlp_url="",  # Optional: https://host/api/public/otel
    langfuse_ui_url="",  # Optional browser link, such as https://host
    metric_queries={},  # Optional named PromQL queries for this project.
)
