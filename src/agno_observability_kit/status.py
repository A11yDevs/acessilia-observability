"""Read the status of independent observability sources."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import httpx

from agno_observability_kit.integrations.agno import AgnoClient, UpstreamError
from agno_observability_kit.integrations.loki import recent_logs
from agno_observability_kit.settings import ProjectConfig


def _seen(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


async def source_status(config: ProjectConfig) -> dict[str, dict[str, str]]:
    async def agentos() -> dict[str, str]:
        if not config.agentos_url:
            return {"state": "not_configured", "detail": "Set agentos_url in config.py"}
        try:
            result = await AgnoClient(config.agentos_url, os.getenv("AGENTOS_TOKEN", "")).discover()
            count = sum(len(result[kind]) for kind in ("agents", "teams", "workflows"))
            return {"state": "connected", "detail": f"{count} components"}
        except UpstreamError as exc:
            return {"state": "unavailable", "detail": exc.detail}

    async def prometheus() -> dict[str, str]:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get("http://prometheus:9090/api/v1/query", params={"query": f'max(timestamp({{project_id="{config.project_id}"}}))'})
                response.raise_for_status()
                data = response.json()
            if data.get("status") != "success":
                raise ValueError("query failed")
            samples = data.get("data", {}).get("result", [])
            if not samples:
                return {"state": "no_data", "detail": "No project metrics"}
            last = max(float(item["value"][1]) for item in samples)
            return {"state": "connected", "detail": "Receiving metrics", "last_seen": _seen(last)}
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            return {"state": "unavailable", "detail": "Prometheus query failed"}

    async def loki() -> dict[str, str]:
        try:
            logs = await recent_logs("http://loki:3100", config.project_id, 1, hours=24)
            if not logs:
                return {"state": "no_data", "detail": "No logs in the last 24 hours"}
            return {"state": "connected", "detail": "Receiving logs", "last_seen": logs[0]["time"]}
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return {"state": "unavailable", "detail": "Loki query failed"}

    async def tempo() -> dict[str, str]:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(
                    "http://tempo:3200/api/search",
                    params={"q": f'{{resource.project_id = "{config.project_id}"}}', "limit": 1},
                )
                response.raise_for_status()
                traces = response.json().get("traces", [])
            if not traces:
                return {"state": "no_data", "detail": "No recent traces"}
            last = int(traces[0]["startTimeUnixNano"]) / 1_000_000_000
            return {"state": "connected", "detail": "Receiving traces", "last_seen": _seen(last)}
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return {"state": "unavailable", "detail": "Tempo search failed"}

    names = ("agentos", "prometheus", "loki", "tempo")
    results = await asyncio.gather(agentos(), prometheus(), loki(), tempo())
    status = dict(zip(names, results))
    status["langfuse"] = (
        {"state": "configured", "detail": "Check collector delivery in Langfuse"}
        if config.langfuse_otlp_url else {"state": "not_configured", "detail": "Optional"}
    )
    return status
