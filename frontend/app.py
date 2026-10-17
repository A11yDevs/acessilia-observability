from __future__ import annotations

import os
import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from config import CONFIG
from agno_observability_kit.integrations.agno import AgnoClient, UpstreamError
from agno_observability_kit.integrations.loki import recent_logs
from agno_observability_kit.integrations.prometheus import query_history, query_metrics
from agno_observability_kit.settings import ProjectConfig
from agno_observability_kit.status import source_status
from frontend.test_console import test_console_routes
from frontend.central import BodyLimit, central_routes, token_equal
from agno_observability_kit.store import EventStore


STATIC = Path(__file__).parent / "static"


def create_app(config: ProjectConfig = CONFIG, store: EventStore | None = None) -> FastAPI:
    store = store or EventStore(config.telemetry_db, config.retention_days, config.max_events)
    @asynccontextmanager
    async def lifespan(app):
        async def maintenance():
            while True:
                await asyncio.to_thread(store.prune)
                await asyncio.sleep(60)
        task = asyncio.create_task(maintenance())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title=f"{config.project_name} Observability", lifespan=lifespan)
    app.state.store = store
    app.add_middleware(BodyLimit)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.include_router(central_routes(config, store))
    if config.enable_test_console:
        app.include_router(test_console_routes(config, lambda: os.getenv("AGENTOS_TOKEN", "")))

    @app.middleware("http")
    async def viewer_auth(request, call_next):
        token = os.getenv('OBS_VIEW_TOKEN', '')
        path = request.url.path
        protected = path.startswith('/api/') and not path.startswith('/api/ingest/') and path not in {'/api/auth/login','/api/auth/logout'}
        if token and protected:
            supplied = request.headers.get('authorization', '')
            cookie = request.cookies.get('obs_session', '')
            if not (token_equal(supplied, f'Bearer {token}') or token_equal(cookie, token)):
                return JSONResponse({'detail':'Autenticação necessária.'}, status_code=401)
        response = await call_next(request)
        if path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Validation responses must not echo rejected credentials or document payloads.
        return JSONResponse(status_code=422, content={'detail':'Evento ou parâmetro inválido.',
            'errors':[{'loc':list(error['loc']), 'type':error['type']} for error in exc.errors()]})

    def agno() -> AgnoClient:
        if not config.agentos_url:
            raise HTTPException(503, "Set agentos_url in config.py")
        return AgnoClient(config.agentos_url, os.getenv("AGENTOS_TOKEN", ""))

    @app.exception_handler(UpstreamError)
    async def upstream_error(_request, exc: UpstreamError):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=502,
            content={"detail": exc.detail, "upstream_status": exc.status_code, "path": exc.path},
        )

    @app.get("/", include_in_schema=False)
    async def home():
        return FileResponse(STATIC / "index.html")

    @app.get("/test", include_in_schema=False)
    async def test_console():
        return FileResponse(STATIC / "test.html")

    @app.get('/docs/integration', include_in_schema=False)
    def integration_guide():
        return FileResponse(Path(__file__).resolve().parents[1] / 'docs' / 'acessilia-integration.md', media_type='text/plain')

    @app.get("/api/config")
    async def public_config():
        return {
            "project_id": config.project_id,
            "project_name": config.project_name,
            "environment": config.environment,
            "configured": bool(config.agentos_url),
            "langfuse_ui_url": config.langfuse_ui_url,
            "grafana_ui_url": config.grafana_ui_url,
            "test_console_enabled": config.enable_test_console,
        }

    @app.get("/api/status")
    async def status():
        return await source_status(config)

    @app.get("/api/entities")
    async def entities():
        return await agno().discover()

    @app.get("/api/sessions")
    async def sessions(
        type: str = "agent", limit: int = Query(20, ge=1, le=100),
        component_id: str = Query("", max_length=200),
    ):
        try:
            return await agno().sessions(type, limit, component_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/sessions/{session_id}/runs")
    async def runs(session_id: str, type: str = "agent"):
        try:
            return await agno().session_runs(session_id, type)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/metrics")
    async def metrics():
        try:
            return await query_metrics("http://prometheus:9090", config.project_id, config.metric_queries)
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, f"Prometheus is unavailable: {type(exc).__name__}") from exc

    @app.get("/api/metrics/range")
    async def metrics_range(hours: int = Query(1, ge=1, le=24)):
        try:
            return await query_history("http://prometheus:9090", config.project_id, hours)
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, f"Prometheus is unavailable: {type(exc).__name__}") from exc

    @app.get("/api/logs")
    async def logs(
        limit: int = Query(50, ge=1, le=200), hours: int = Query(1, ge=1, le=24),
        text: str = Query("", max_length=200), level: Literal["", "error", "warn", "info", "debug"] = "",
    ):
        try:
            return await recent_logs("http://loki:3100", config.project_id, limit, hours=hours, text=text, level=level)
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, f"Loki is unavailable: {type(exc).__name__}") from exc

    return app


app = create_app()
