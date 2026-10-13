import asyncio
import importlib.util
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from agno_observability_kit.integrations.agno import AgnoClient


@unittest.skipUnless(
    importlib.util.find_spec("agno") and importlib.util.find_spec("sqlalchemy") and importlib.util.find_spec("openai"),
    "install agno[os,openai] for the live AgentOS adapter check",
)
class LiveAgnoTests(unittest.TestCase):
    def test_example_matches_agno_3_api(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "AGENTOS_DB_FILE": str(Path(directory) / "agentos.db"), "OTLP_COLLECTOR_URL": "",
        }):
            app = runpy.run_path(str(Path(__file__).parents[1] / "examples" / "agentos_app.py"))["app"]
            with TestClient(app):
                client = AgnoClient("http://agentos", transport=httpx.ASGITransport(app=app))
                components = asyncio.run(client.discover())
                sessions = asyncio.run(client.sessions("agent"))
            self.assertEqual(components["version"].split(".")[0], "3")
            self.assertEqual(components["agents"][0]["name"], "Example agent")
            self.assertEqual(sessions["data"], [])


if __name__ == "__main__":
    unittest.main()
