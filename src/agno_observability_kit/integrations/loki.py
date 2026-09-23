from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

import httpx


async def recent_logs(
    base_url: str, project_id: str, limit: int = 50, *, hours: int = 1,
    text: str = "", level: str = "", transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    if level not in {"", "error", "warn", "info", "debug"}:
        raise ValueError("level must be error, warn, info or debug")
    query = f'{{project_id="{project_id}"}}'
    if text:
        query += f" |= {json.dumps(text)}"
    if level:
        query += f' |~ "(?i){level}"'
    end = time.time_ns()
    async with httpx.AsyncClient(timeout=8, transport=transport) as client:
        response = await client.get(
            f"{base_url.rstrip('/')}/loki/api/v1/query_range",
            params={"query": query, "limit": limit, "direction": "BACKWARD", "start": end - hours * 3600 * 1_000_000_000, "end": end},
        )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "success":
        raise ValueError("Loki rejected the log query")
    entries = []
    for stream in payload.get("data", {}).get("result", []):
        labels = stream.get("stream", {})
        for value in stream.get("values", []):
            if len(value) < 2:
                continue
            timestamp, message = value[:2]
            metadata = value[2] if len(value) > 2 and isinstance(value[2], dict) else {}
            entries.append({
                "timestamp": timestamp,
                "time": datetime.fromtimestamp(int(timestamp) / 1_000_000_000, tz=timezone.utc).isoformat(),
                "message": message,
                "labels": labels,
                "trace_id": metadata.get("trace_id") or labels.get("trace_id"),
                "run_id": metadata.get("run_id") or labels.get("run_id"),
            })
    return sorted(entries, key=lambda entry: entry["timestamp"], reverse=True)[:limit]
