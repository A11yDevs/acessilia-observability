from __future__ import annotations

from typing import Any

import httpx


async def recent_logs(base_url: str, project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    query = f'{{project_id="{project_id}"}}'
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.get(
            f"{base_url.rstrip('/')}/loki/api/v1/query_range",
            params={"query": query, "limit": limit, "direction": "BACKWARD"},
        )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "success":
        raise ValueError("Loki rejected the log query")
    entries = []
    for stream in payload.get("data", {}).get("result", []):
        labels = stream.get("stream", {})
        for timestamp, message in stream.get("values", []):
            entries.append({"timestamp": timestamp, "message": message, "labels": labels})
    return sorted(entries, key=lambda entry: entry["timestamp"], reverse=True)[:limit]

