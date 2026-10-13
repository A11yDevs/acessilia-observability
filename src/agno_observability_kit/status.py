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


def _sample(series: list[dict]) -> float | None:
    return float(series[0]["value"][1]) if series else None


async def source_status(config: ProjectConfig) -> dict[str, dict[str, str]]:
    async def prometheus_query(expression: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get("http://prometheus:9090/api/v1/query", params={"query": expression})
            response.raise_for_status()
            data = response.json()
        if data.get("status") != "success":
            raise ValueError("Prometheus query failed")
        return data.get("data", {}).get("result", [])

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
            samples = await prometheus_query(f'max(timestamp({{project_id="{config.project_id}"}}))')
            if not samples:
                return {"state": "no_data", "detail": "No project metrics"}
            last = max(float(item["value"][1]) for item in samples)
            return {"state": "connected", "detail": "Receiving metrics", "last_seen": _seen(last)}
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            return {"state": "unavailable", "detail": "Prometheus query failed"}

    async def collector() -> dict[str, str]:
        try:
            result = await prometheus_query(f'up{{job="prometheus.scrape.collector",project_id="{config.project_id}"}}')
            if not result:
                return {"state": "no_data", "detail": "No Alloy heartbeat; check the collector and remote write"}
            if any(float(item["value"][1]) == 1 for item in result):
                return {"state": "connected", "detail": "Alloy heartbeat received"}
            return {"state": "unavailable", "detail": "Alloy self scrape failed"}
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            return {"state": "unavailable", "detail": "Cannot check Alloy heartbeat"}

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

    async def langfuse() -> dict[str, str]:
        if not config.langfuse_otlp_url:
            return {"state": "not_configured", "detail": "Optional"}
        selector = f'component_id="otelcol.exporter.otlphttp.langfuse",project_id="{config.project_id}"'
        try:
            delivered, failed, queued = await asyncio.gather(
                prometheus_query(f'sum(otelcol_exporter_sent_spans_total{{{selector}}})'),
                prometheus_query(f'sum(increase(otelcol_exporter_send_failed_spans_total{{{selector}}}[15m]))'),
                prometheus_query(f'max(otelcol_exporter_queue_size{{{selector},data_type="traces"}})'),
            )
            sent_count = int(_sample(delivered) or 0)
            failed_count = int(_sample(failed) or 0)
            queue_size = int(_sample(queued) or 0)
            if failed_count or queue_size:
                return {"state": "degraded", "detail": f"{failed_count} spans in failed exports (15m); {queue_size} batches queued"}
            if sent_count:
                return {"state": "delivered", "detail": f"{sent_count} spans accepted by the Langfuse endpoint"}
            return {"state": "no_data", "detail": "No Langfuse traces exported yet"}
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            return {"state": "unavailable", "detail": "Cannot check Langfuse exporter"}

    names = ("agentos", "prometheus", "collector", "loki", "tempo", "langfuse")
    results = await asyncio.gather(agentos(), prometheus(), collector(), loki(), tempo(), langfuse())
    return dict(zip(names, results))
