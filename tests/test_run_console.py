import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from agno_observability_kit.integrations.agno import AgnoClient
from agno_observability_kit.integrations.agno_runs import stream_run
from agno_observability_kit.settings import ProjectConfig
from frontend.app import create_app


class RunConsoleTests(unittest.TestCase):
    def test_streams_each_registered_component_with_session_and_server_side_token(self):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b'event: RunContent\ndata: {"content":"Hello"}\n\n',
            )

        transport = httpx.MockTransport(handle)
        for kind, route in (("agent", "agents"), ("team", "teams"), ("workflow", "workflows")):
            async def collect():
                return b"".join([
                    chunk async for chunk in stream_run(
                        "http://agent.test", "secret", kind, "echo", "Hi", "test-session", transport
                    )
                ])

            self.assertIn(b"event: RunContent", asyncio.run(collect()))
            request = requests[-1]
            self.assertEqual(request.url.path, f"/{route}/echo/runs")
            self.assertEqual(request.headers["Authorization"], "Bearer secret")
            self.assertIn(b"test-session", request.content)
            self.assertIn(b"Hi", request.content)
            self.assertIn(b"stream", request.content)

    def test_reports_rejected_credentials_inside_stream_without_upstream_body(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(401, text="private detail"))

        async def collect():
            return b"".join([
                chunk async for chunk in stream_run(
                    "http://agent.test", "wrong", "agent", "echo", "Hi", "s1", transport
                )
            ])

        output = asyncio.run(collect())
        self.assertIn(b"event: error", output)
        self.assertIn(b"rejected the execution credential", output)
        self.assertNotIn(b"private detail", output)

    def test_rejects_non_stream_response(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"content": "unexpected"}))

        async def collect():
            return b"".join([
                chunk async for chunk in stream_run(
                    "http://agent.test", "", "agent", "echo", "Hi", "s1", transport
                )
            ])

        output = asyncio.run(collect())
        self.assertIn(b"event: error", output)
        self.assertIn(b"did not return an event stream", output)
        self.assertNotIn(b"unexpected", output)

    def test_endpoint_requires_agentos_and_validates_request(self):
        app = create_app(ProjectConfig())

        async def call(payload):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                return await client.post("/api/tests/runs", json=payload)

        valid = {"entity_type": "agent", "entity_id": "echo", "message": "Hi"}
        self.assertEqual(asyncio.run(call(valid)).status_code, 503)
        self.assertEqual(asyncio.run(call({**valid, "entity_type": "step"})).status_code, 422)
        self.assertEqual(asyncio.run(call({**valid, "message": ""})).status_code, 422)

    def test_route_assigns_reusable_session_id(self):
        async def fake_stream(*args, **kwargs):
            yield b'event: RunCompleted\ndata: {"content":"Done"}\n\n'

        app = create_app(ProjectConfig(agentos_url="http://agent.test"))

        async def call():
            with patch("frontend.test_console.stream_run", fake_stream):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    return await client.post(
                        "/api/tests/runs",
                        json={"entity_type": "workflow", "entity_id": "echo", "message": "Hi"},
                    )

        response = asyncio.run(call())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["X-Session-Id"].startswith("test-"))
        self.assertEqual(response.headers["Content-Type"], "text/event-stream; charset=utf-8")
        self.assertIn(b"RunCompleted", response.content)

    @unittest.skipUnless(
        importlib.util.find_spec("agno") and importlib.util.find_spec("sqlalchemy"),
        "install agno[os] for the local workflow check",
    )
    def test_real_model_free_workflow_stream_and_persisted_results(self):
        from agno.db.sqlite import SqliteDb
        from agno.os import AgentOS
        from agno.workflow import Step, StepInput, StepOutput, Workflow

        def echo(step_input: StepInput) -> StepOutput:
            return StepOutput(content=str(step_input.input))

        with tempfile.TemporaryDirectory() as directory:
            db = SqliteDb(db_file=str(Path(directory) / "agentos.db"))
            workflow = Workflow(id="echo", db=db, steps=[Step(name="Echo", executor=echo)])
            app = AgentOS(db=db, workflows=[workflow]).get_app()
            with TestClient(app):
                transport = httpx.ASGITransport(app=app)

                async def run_and_read():
                    events = b"".join([
                        chunk async for chunk in stream_run(
                            "http://agent.test", "", "workflow", "echo", "Hello", "test-session", transport
                        )
                    ])
                    client = AgnoClient("http://agent.test", transport=transport)
                    sessions = await client.sessions("workflow", component_id="echo")
                    runs = await client.session_runs("test-session", "workflow")
                    return events, sessions, runs

                events, sessions, runs = asyncio.run(run_and_read())
            self.assertIn(b"event: StepStarted", events)
            self.assertIn(b"event: WorkflowCompleted", events)
            self.assertEqual(sessions["data"][0]["session_id"], "test-session")
            self.assertEqual(runs[0]["run_input"], "Hello")
            self.assertTrue(any(event["event"] == "StepStarted" for event in runs[0]["events"]))


if __name__ == "__main__":
    unittest.main()
