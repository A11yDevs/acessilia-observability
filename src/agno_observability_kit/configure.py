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
    hub_dir = root / "infra/hub"
    hub_dir.mkdir(parents=True, exist_ok=True)
    edge = root / "infra/edge"
    edge.mkdir(parents=True, exist_ok=True)
    loadtest = root / "infra/loadtest"
    loadtest.mkdir(parents=True, exist_ok=True)
    log_dir = Path(config.edge_log_dir) if config.edge_log_dir else edge / "logs"
    if not config.edge_log_dir:
        log_dir.mkdir(exist_ok=True)
    (hub_dir / ".runtime.env").write_text(
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
