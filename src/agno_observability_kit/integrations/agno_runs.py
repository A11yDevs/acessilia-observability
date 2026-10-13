"""Stream an explicitly requested AgentOS run without storing its content."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from urllib.parse import quote

import httpx


ROUTES = {"agent": "agents", "team": "teams", "workflow": "workflows"}


def _error(detail: str) -> bytes:
    return f"event: error\ndata: {json.dumps({'error': detail})}\n\n".encode()


async def stream_run(
    base_url: str,
    token: str,
    entity_type: str,
    entity_id: str,
    message: str,
    session_id: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[bytes]:
    route = ROUTES[entity_type]
    path = f"/{route}/{quote(entity_id, safe='')}/runs"
    headers = {"Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    fields = {"message": message, "stream": "true", "session_id": session_id}
    request_body = {"data": fields} if entity_type == "workflow" else {
        "files": {key: (None, value) for key, value in fields.items()}
    }
    timeout = httpx.Timeout(connect=8, read=300, write=30, pool=8)
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            async with client.stream(
                "POST", f"{base_url.rstrip('/')}{path}", headers=headers, **request_body
            ) as response:
                if response.status_code >= 400:
                    if response.status_code in {401, 403}:
                        yield _error("AgentOS rejected the execution credential")
                    else:
                        yield _error(f"AgentOS returned HTTP {response.status_code}")
                    return
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    yield _error("AgentOS did not return an event stream")
                    return
                async for chunk in response.aiter_bytes():
                    yield chunk
    except httpx.HTTPError as exc:
        yield _error(f"AgentOS run stream failed: {type(exc).__name__}")
