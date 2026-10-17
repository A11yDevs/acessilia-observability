"""Read-only adapters for the actual develop REST contracts, with isolated failures."""
import asyncio
import os
import time

import httpx


class EcosystemClient:
    def __init__(self, config, transport=None):
        self.config, self.transport = config, transport
        self.cached = None
        self.cached_at = 0
        self.lock = asyncio.Lock()

    async def snapshot(self):
        async with self.lock:
            if self.cached is not None and time.monotonic() - self.cached_at < 30:
                return self.cached
            acessilia, toolbox = await asyncio.gather(
                self._service("acessilia", self.config.acessilia_url, "/api/v1", "ACESSILIA_OBSERVABILITY_TOKEN"),
                self._service("acessilia-toolbox", self.config.toolbox_url, "/v1", "TOOLBOX_API_KEY"),
            )
            self.cached = {"acessilia": acessilia, "toolbox": toolbox}
            self.cached_at = time.monotonic()
            return self.cached

    async def _service(self, service, url, prefix, token_name):
        if not url:
            return {"state": "not_configured", "detail": "Preencha a URL e o token no .env.", "endpoints": {}}
        token = os.getenv(token_name, "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        paths = ["health", "stats"] if service == "acessilia" else ["health", "capabilities", "providers"]
        async with httpx.AsyncClient(timeout=5, transport=self.transport, follow_redirects=False, headers=headers) as client:
            async def read(path):
                try:
                    async with client.stream("GET", f"{url.rstrip('/')}{prefix}/{path}") as response:
                        if response.status_code != 200:
                            return path, {"state": "unauthorized" if response.status_code in {401,403} else "unavailable", "http_status": response.status_code}
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > 1_000_000:
                                raise ValueError("Response too large")
                        import json
                        payload = json.loads(data)
                        value = _public_payload(service, path, payload)
                    return path, {"state": "connected", "data": value}
                except (httpx.HTTPError, ValueError, TypeError, KeyError):
                    return path, {"state": "unavailable", "detail": "Falha de conexão ou contrato incompatível."}
            endpoints = dict(await asyncio.gather(*(read(path) for path in paths)))
        health = endpoints['health']
        state = health['state']
        if state == "connected" and (health['data'].get('status') not in {'ok', 'healthy'} or health['data'].get('model_reachable') is False):
            state = "degraded"
        if state == "connected" and any(item['state'] != 'connected' for item in endpoints.values()):
            state = "degraded"
        return {"state": state, "detail": "Consultas REST somente de leitura; decisões e jobs chegam por eventos.", "endpoints": endpoints}


def _public_payload(service, path, payload):
    if path in {"capabilities", "providers"}:
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise ValueError("Expected registry list")
        keys = {"id", "version", "deterministic", "cacheable", "providers"}
        # Do not forward provider endpoints, credentials, environment or arbitrary config.
        return [{key: item[key] for key in keys if key in item} for item in payload[:500]]
    if not isinstance(payload, dict):
        raise ValueError("Expected object")
    keys = {"status", "version", "queue_size", "model_reachable", "model_client", "model_name", "git_commit"} if path == "health" else {"total", "sucesso", "erros", "tempo_medio_segundos"}
    if path == "health" and not isinstance(payload.get("status"), str):
        raise ValueError("Health must declare status")
    return {key: payload[key] for key in keys if key in payload}
