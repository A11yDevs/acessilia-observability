import asyncio
import unittest

import httpx

from kit.panel import create_app
from kit.settings import ProjectConfig


class PanelTests(unittest.TestCase):
    def test_branding_and_missing_target(self):
        app = create_app(ProjectConfig(project_id="sample", project_name="Sample project"))

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                config = await client.get("/api/config")
                entities = await client.get("/api/entities")
                page = await client.get("/")
            return config, entities, page

        config, entities, page = asyncio.run(run())
        self.assertEqual(config.json()["project_name"], "Sample project")
        self.assertEqual(entities.status_code, 503)
        self.assertEqual(page.status_code, 200)


if __name__ == "__main__":
    unittest.main()
