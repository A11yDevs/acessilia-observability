"""Small AgentOS application for checking discovery and optional OTLP export."""

from __future__ import annotations

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

from agno_observability_kit.instrumentation.agno import configure_agno_telemetry


collector_url = os.getenv("OTLP_COLLECTOR_URL", "")
if collector_url:
    configure_agno_telemetry(
        service_name="example-agentos",
        project_id=os.getenv("PROJECT_ID", "example"),
        environment=os.getenv("ENVIRONMENT", "local"),
        collector_url=collector_url,
    )

db = SqliteDb(db_file=os.getenv("AGENTOS_DB_FILE", "example-agentos.db"))
app = AgentOS(
    name="Example AgentOS",
    agents=[Agent(name="Example agent", db=db)],
    db=db,
).get_app()
