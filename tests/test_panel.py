import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from frontend.app import create_app
from agno_observability_kit.settings import ProjectConfig


class PanelTests(unittest.TestCase):
    def test_branding_and_missing_target(self):
        app = create_app(ProjectConfig(
            project_id="sample", project_name="Sample project",
            langfuse_ui_url="https://trace.example",
        ))

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                config = await client.get("/api/config")
                entities = await client.get("/api/entities")
                page = await client.get("/")
            return config, entities, page

        config, entities, page = asyncio.run(run())
        self.assertEqual(config.json()["project_name"], "Sample project")
        self.assertEqual(config.json()["langfuse_ui_url"], "https://trace.example")
        self.assertEqual(config.json()["grafana_ui_url"], "http://localhost:3000")
        self.assertEqual(entities.status_code, 503)
        self.assertEqual(page.status_code, 200)

    def test_range_limits_and_source_status(self):
        app = create_app(ProjectConfig())

        async def run():
            with patch("frontend.app.source_status", new=AsyncMock(return_value={"tempo": {"state": "no_data"}})):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    return (
                        await client.get("/api/status"),
                        await client.get("/api/metrics/range?hours=25"),
                        await client.get("/api/logs?level=invalid"),
                    )

        status, range_response, logs = asyncio.run(run())
        self.assertEqual(status.json()["tempo"]["state"], "no_data")
        self.assertEqual(range_response.status_code, 422)
        self.assertEqual(logs.status_code, 422)


if __name__ == "__main__":
    unittest.main()
