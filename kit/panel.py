from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import CONFIG
from kit.agno import AgnoClient, UpstreamError
from kit.logs import recent_logs
from kit.metrics import query_metrics
from kit.settings import ProjectConfig


STATIC = Path(__file__).parent / "static"


def create_app(config: ProjectConfig = CONFIG) -> FastAPI:
    app = FastAPI(title=f"{config.project_name} Observability")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

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

    @app.get("/api/config")
    async def public_config():
        return {
            "project_id": config.project_id,
            "project_name": config.project_name,
            "environment": config.environment,
            "configured": bool(config.agentos_url),
            "langfuse_ui_url": config.langfuse_ui_url,
        }

    @app.get("/api/entities")
    async def entities():
        return await agno().discover()

    @app.get("/api/sessions")
    async def sessions(type: str = "agent", limit: int = Query(20, ge=1, le=100)):
        try:
            return await agno().sessions(type, limit)
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

    @app.get("/api/logs")
    async def logs(limit: int = Query(50, ge=1, le=200)):
        try:
            return await recent_logs("http://loki:3100", config.project_id, limit)
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, f"Loki is unavailable: {type(exc).__name__}") from exc

    return app


app = create_app()
