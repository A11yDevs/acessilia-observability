"""Check the network paths used by a remote observability installation."""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

from config import CONFIG
from agno_observability_kit.integrations.agno import AgnoClient, UpstreamError
from agno_observability_kit.settings import ProjectConfig


def _tcp(label: str, host: str, port: int) -> tuple[str, bool, str]:
    try:
        with socket.create_connection((host, port), timeout=3):
            return label, True, f"{host}:{port} reachable"
    except socket.gaierror:
        return label, False, f"DNS could not resolve {host}"
    except (OSError, TimeoutError) as exc:
        return label, False, f"{host}:{port} unreachable ({type(exc).__name__})"


def _url_target(label: str, url: str) -> tuple[str, bool, str]:
    parsed = urlparse(url)
    return _tcp(label, parsed.hostname or "", parsed.port or (443 if parsed.scheme == "https" else 80))


def application_checks(config: ProjectConfig = CONFIG, root: Path | None = None) -> list[tuple[str, bool, str]]:
    server = config.observability_ingest_url.rstrip("/")
    checks = [_tcp("Local Alloy OTLP", config.collector_bind_ip, 4318)]
    for label, port in (("Prometheus ingestion", 9090), ("Loki ingestion", 3100), ("Tempo ingestion", 4318)):
        checks.append(_url_target(label, f"{server}:{port}"))
    if config.langfuse_otlp_url:
        checks.append(_url_target("Langfuse ingestion", config.langfuse_otlp_url))
        credentials = (root or Path(__file__).resolve().parents[2]) / "infra/application-collector/.env"
        values = {}
        if credentials.is_file():
            for line in credentials.read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip().strip('"\'')
        ready = all(values.get(key) for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"))
        checks.append(("Langfuse credentials", bool(ready), "present" if ready else "set both keys in infra/application-collector/.env"))
    return checks


async def server_checks(config: ProjectConfig = CONFIG) -> list[tuple[str, bool, str]]:
    if not config.agentos_url:
        agentos = ("AgentOS", False, "set agentos_url in config.py")
    else:
        try:
            client = AgnoClient(config.agentos_url, os.getenv("AGENTOS_TOKEN", ""))
            info = await client.get("/info")
            if not isinstance(info, dict):
                raise UpstreamError("/info", 200, "AgentOS metadata has an unexpected shape")
            entities = await client.discover()
            counts = ", ".join(f"{kind}: {len(entities[kind])}" for kind in ("agents", "teams", "workflows"))
            agentos = ("AgentOS", True, counts)
        except UpstreamError as exc:
            agentos = ("AgentOS", False, exc.detail)
    return [
        agentos,
        _tcp("Prometheus", "prometheus", 9090),
        _tcp("Loki", "loki", 3100),
        _tcp("Tempo", "tempo", 3200),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("server", "application"))
    args = parser.parse_args()
    checks = asyncio.run(server_checks()) if args.role == "server" else application_checks()
    for label, ok, detail in checks:
        print(f"{'OK' if ok else 'FAIL'} {label}: {detail}")
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
