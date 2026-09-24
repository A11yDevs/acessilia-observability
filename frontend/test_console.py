"""Routes used only by the interactive AgentOS test console."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Literal

from agno_observability_kit.integrations.agno_runs import stream_run
from agno_observability_kit.settings import ProjectConfig


class TestRun(BaseModel):
    entity_type: Literal["agent", "team", "workflow"]
    entity_id: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=100_000)
    session_id: str | None = Field(default=None, min_length=1, max_length=200)


def test_console_routes(config: ProjectConfig, token: Callable[[], str]) -> APIRouter:
    router = APIRouter()

    @router.post("/api/tests/runs")
    async def run(request: TestRun):
        if not config.agentos_url:
            raise HTTPException(503, "Set agentos_url in config.py")
        session_id = request.session_id or f"test-{uuid4()}"
        return StreamingResponse(
            stream_run(
                config.agentos_url,
                token(),
                request.entity_type,
                request.entity_id,
                request.message,
                session_id,
            ),
            media_type="text/event-stream",
            headers={"X-Session-Id": session_id, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
