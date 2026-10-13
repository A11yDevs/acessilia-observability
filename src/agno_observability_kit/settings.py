from __future__ import annotations

import re
import ipaddress
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class ProjectConfig:
    project_id: str = "example"
    project_name: str = "Example project"
    environment: str = "local"
    agentos_url: str = ""
    observability_bind_ip: str = "127.0.0.1"
    observability_ingest_url: str = "http://host.docker.internal"
    collector_bind_ip: str = "127.0.0.1"
    metrics_target: str = ""
    metrics_path: str = "/metrics"
    collector_log_dir: str = ""
    collector_log_glob: str = "*.log"
    langfuse_otlp_url: str = ""
    langfuse_ui_url: str = ""
    langfuse_bind_ip: str = "127.0.0.1"
    langfuse_ui_port: int = 3001
    langfuse_media_port: int = 9092
    langfuse_media_url: str = "http://localhost:9092"
    grafana_ui_url: str = "http://localhost:3000"
    metric_queries: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for label, value in (("project_id", self.project_id), ("environment", self.environment)):
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", value):
                raise ValueError(f"{label} must contain only letters, digits, dots, underscores or hyphens")
        if not self.project_name.strip():
            raise ValueError("project_name cannot be empty")
        for label, value in (
            ("agentos_url", self.agentos_url),
            ("observability_ingest_url", self.observability_ingest_url),
            ("langfuse_otlp_url", self.langfuse_otlp_url),
            ("langfuse_ui_url", self.langfuse_ui_url),
            ("langfuse_media_url", self.langfuse_media_url),
            ("grafana_ui_url", self.grafana_ui_url),
        ):
            if value and (urlparse(value).scheme not in {"http", "https"} or not urlparse(value).netloc):
                raise ValueError(f"{label} must be an HTTP(S) URL")
            if value and (urlparse(value).username or urlparse(value).password):
                raise ValueError(f"{label} cannot contain credentials")
        if self.langfuse_otlp_url:
            langfuse = urlparse(self.langfuse_otlp_url)
            if langfuse.path.rstrip("/") != "/api/public/otel" or langfuse.query or langfuse.fragment:
                raise ValueError("langfuse_otlp_url must end in /api/public/otel without a query or fragment")
        for label, value in (
            ("observability_bind_ip", self.observability_bind_ip),
            ("collector_bind_ip", self.collector_bind_ip),
            ("langfuse_bind_ip", self.langfuse_bind_ip),
        ):
            try:
                ipaddress.IPv4Address(value)
            except ValueError as exc:
                raise ValueError(f"{label} must be an IPv4 address") from exc
        for label, value in (("langfuse_ui_port", self.langfuse_ui_port), ("langfuse_media_port", self.langfuse_media_port)):
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 65535:
                raise ValueError(f"{label} must be a TCP port")
        server = urlparse(self.observability_ingest_url)
        if server.scheme != "http" or server.port or server.path or server.query or server.username:
            raise ValueError("observability_ingest_url must be an http://host address without a port or path")
        if self.metrics_target:
            target = urlparse(f"http://{self.metrics_target}")
            try:
                valid = target.hostname and target.port and target.netloc == self.metrics_target and not target.path
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("metrics_target must be a host:port value")
        if not self.metrics_path.startswith("/"):
            raise ValueError("metrics_path must start with /")
        if "/" in self.collector_log_glob or ".." in self.collector_log_glob:
            raise ValueError("collector_log_glob must match files within collector_log_dir")
        if self.collector_log_dir and not Path(self.collector_log_dir).is_absolute():
            raise ValueError("collector_log_dir must be an absolute path")
