from __future__ import annotations

import math
import time
from typing import Any

import httpx


async def query_metrics(base_url: str, project_id: str, queries: dict[str, str]) -> dict[str, Any]:
    all_queries = {
        "Metric series": f'count({{project_id="{project_id}"}})',
        "Targets up": f'up{{project_id="{project_id}"}}',
        **queries,
    }
    result: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=8) as client:
        for name, expression in all_queries.items():
            response = await client.get(f"{base_url.rstrip('/')}/api/v1/query", params={"query": expression})
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != "success":
                raise ValueError("Prometheus rejected a configured query")
            series = payload.get("data", {}).get("result", [])
            values = []
            for item in series:
                sample = item.get("value")
                if isinstance(sample, list) and len(sample) == 2:
                    try:
                        value = float(sample[1])
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(value):
                        values.append({"labels": item.get("metric", {}), "value": value})
            result[name] = values
    return result


async def query_history(base_url: str, project_id: str, hours: int, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    selector = f'project_id="{project_id}"'
    queries = {
        "Run rate": f'sum(rate(agno_runs_total{{{selector}}}[5m]))',
        "Error rate": f'(sum(rate(agno_runs_total{{{selector},status="error"}}[5m])) or vector(0)) / clamp_min(sum(rate(agno_runs_total{{{selector}}}[5m])), 0.001)',
        "P95 duration": f'histogram_quantile(0.95, sum by (le) (rate(agno_run_duration_seconds_bucket{{{selector}}}[5m])))',
    }
    end = int(time.time())
    start = end - hours * 3600
    step = max(30, hours * 3600 // 90)
    result: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=8, transport=transport) as client:
        for name, expression in queries.items():
            response = await client.get(
                f"{base_url.rstrip('/')}/api/v1/query_range",
                params={"query": expression, "start": start, "end": end, "step": step},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != "success":
                raise ValueError("Prometheus rejected a range query")
            points = []
            for series in payload.get("data", {}).get("result", []):
                for stamp, raw in series.get("values", []):
                    try:
                        value = float(raw)
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(value):
                        points.append({"time": stamp, "value": value})
            result[name] = sorted(points, key=lambda point: point["time"])
    return result
