"""Write runtime settings from the project configuration."""

from __future__ import annotations

import json
from pathlib import Path

from config import CONFIG
from agno_observability_kit.alloy import render_alloy
from agno_observability_kit.settings import ProjectConfig


ROOT = Path(__file__).resolve().parents[2]


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def write_config(config: ProjectConfig = CONFIG, root: Path = ROOT) -> None:
    server_dir = root / "infra/observability-server"
    server_dir.mkdir(parents=True, exist_ok=True)
    collector = root / "infra/application-collector"
    collector.mkdir(parents=True, exist_ok=True)
    performance_tests = root / "infra/performance-tests"
    performance_tests.mkdir(parents=True, exist_ok=True)
    log_dir = config.collector_log_dir or "./logs"
    if not config.collector_log_dir:
        (collector / "logs").mkdir(exist_ok=True)
    (server_dir / ".runtime.env").write_text(
        f"OBSERVABILITY_BIND_IP={config.observability_bind_ip}\n"
        f"LANGFUSE_BIND_IP={config.langfuse_bind_ip}\n"
        f"LANGFUSE_UI_PORT={config.langfuse_ui_port}\n"
        f"LANGFUSE_MEDIA_PORT={config.langfuse_media_port}\n"
        f"LANGFUSE_UI_URL={_quoted(config.langfuse_ui_url or f'http://localhost:{config.langfuse_ui_port}')}\n"
        f"LANGFUSE_MEDIA_URL={_quoted(config.langfuse_media_url)}\n"
    )
    (collector / ".runtime.env").write_text(
        f"COLLECTOR_LOG_DIR={_quoted(log_dir)}\nCOLLECTOR_BIND_IP={config.collector_bind_ip}\n"
    )
    (collector / "generated.alloy").write_text(render_alloy(config))
    (performance_tests / ".runtime.env").write_text(f"LOCUST_TARGET_URL={_quoted(config.agentos_url)}\n")


if __name__ == "__main__":
    write_config()
    print("Wrote runtime settings for observability server, application collector and performance tests")
