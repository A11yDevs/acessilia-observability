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
    hub_bind_ip: str = "127.0.0.1"
    hub_ingest_url: str = "http://host.docker.internal"
    metrics_target: str = ""
    metrics_path: str = "/metrics"
    edge_log_dir: str = ""
    edge_log_glob: str = "*.log"
    metric_queries: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for label, value in (("project_id", self.project_id), ("environment", self.environment)):
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", value):
                raise ValueError(f"{label} must contain only letters, digits, dots, underscores or hyphens")
        if not self.project_name.strip():
            raise ValueError("project_name cannot be empty")
        for label, value in (("agentos_url", self.agentos_url), ("hub_ingest_url", self.hub_ingest_url)):
            if value and (urlparse(value).scheme not in {"http", "https"} or not urlparse(value).netloc):
                raise ValueError(f"{label} must be an HTTP(S) URL")
        try:
            ipaddress.ip_address(self.hub_bind_ip)
        except ValueError as exc:
            raise ValueError("hub_bind_ip must be an IP address") from exc
        hub = urlparse(self.hub_ingest_url)
        if hub.scheme != "http" or hub.port or hub.path or hub.query or hub.username:
            raise ValueError("hub_ingest_url must be an http://host address without a port or path")
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
        if "/" in self.edge_log_glob or ".." in self.edge_log_glob:
            raise ValueError("edge_log_glob must match files within edge_log_dir")
        if self.edge_log_dir and not Path(self.edge_log_dir).is_absolute():
            raise ValueError("edge_log_dir must be an absolute path")
