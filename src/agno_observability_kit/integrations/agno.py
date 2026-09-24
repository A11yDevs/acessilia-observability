from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


class UpstreamError(Exception):
    def __init__(self, path: str, status_code: int | None, detail: str) -> None:
        super().__init__(detail)
        self.path = path
        self.status_code = status_code
        self.detail = detail


class AgnoClient:
    def __init__(self, base_url: str, token: str = "", transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.transport = transport

    async def get(self, path: str, *, params: dict[str, Any] | None = None, optional: bool = False) -> Any:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            async with httpx.AsyncClient(timeout=8, transport=self.transport) as client:
                response = await client.get(f"{self.base_url}{path}", headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise UpstreamError(path, None, f"AgentOS is unreachable: {type(exc).__name__}") from exc
        if response.status_code == 404 and optional:
            return None
        if response.status_code in {401, 403}:
            raise UpstreamError(path, response.status_code, "AgentOS rejected the monitoring credential")
        if response.status_code >= 400:
            raise UpstreamError(path, response.status_code, f"AgentOS returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamError(path, response.status_code, "AgentOS returned invalid JSON") from exc

    async def discover(self) -> dict[str, Any]:
        info = await self.get("/info", optional=True) or {}
        config = await self.get("/config", optional=True) or {}
        if not isinstance(info, dict) or not isinstance(config, dict):
            raise UpstreamError("/config", 200, "AgentOS metadata has an unexpected shape")
        result: dict[str, Any] = {
            "version": info.get("agno_version"),
            "auth_mode": info.get("auth_mode"),
            "name": config.get("name") or config.get("os_id"),
        }
        for kind in ("agents", "teams", "workflows"):
            items = config.get(kind)
            if not isinstance(items, list):
                payload = await self.get(f"/{kind}", optional=True)
                items = _items(payload, kind)
            result[kind] = [_entity(item, kind) for item in items if isinstance(item, dict)]
        return result

    async def sessions(self, kind: str, limit: int = 20, component_id: str = "") -> dict[str, Any]:
        _check_kind(kind)
        params: dict[str, Any] = {"type": kind, "limit": limit}
        if component_id:
            params["component_id"] = component_id
        payload = await self.get("/sessions", params=params)
        if isinstance(payload, list):
            return {"data": payload, "meta": {}}
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            return {"data": payload["data"], "meta": payload.get("meta") or {}}
        raise UpstreamError("/sessions", 200, "AgentOS sessions have an unexpected shape")

    async def session_runs(self, session_id: str, kind: str) -> list[dict[str, Any]]:
        _check_kind(kind)
        path = f"/sessions/{quote(session_id, safe='')}/runs"
        payload = await self.get(path, params={"type": kind})
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        raise UpstreamError(path, 200, "AgentOS runs have an unexpected shape")


def _check_kind(kind: str) -> None:
    if kind not in {"agent", "team", "workflow"}:
        raise ValueError("type must be agent, team or workflow")


def _items(payload: Any, kind: str) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in (kind, "data", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def _entity(item: dict[str, Any], kind: str) -> dict[str, str]:
    singular = kind[:-1] if kind != "workflows" else "workflow"
    identifier = item.get("id") or item.get(f"{singular}_id") or item.get("name") or "unknown"
    return {"id": str(identifier), "name": str(item.get("name") or identifier), "type": singular}
