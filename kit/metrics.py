from __future__ import annotations

import math
from typing import Any

import httpx


async def query_metrics(base_url: str, project_id: str, queries: dict[str, str]) -> dict[str, Any]:
    all_queries = {"Targets up": f'up{{project_id="{project_id}"}}', **queries}
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

