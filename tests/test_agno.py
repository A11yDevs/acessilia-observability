import asyncio
import unittest

import httpx

from kit.agno import AgnoClient, UpstreamError
from kit.settings import ProjectConfig


class ConfigTests(unittest.TestCase):
    def test_rejects_invalid_labels_and_urls(self):
        with self.assertRaises(ValueError):
            ProjectConfig(project_id="bad name")
        with self.assertRaises(ValueError):
            ProjectConfig(agentos_url="example.test")


class AgnoTests(unittest.TestCase):
    def test_discovers_components_and_falls_back_when_config_is_unavailable(self):
        def handle(request):
            responses = {
                "/info": {"agno_version": "3.1.0", "auth_mode": "jwt"},
                "/agents": [{"agent_id": "helper", "name": "Helper"}],
                "/teams": {"data": []},
                "/workflows": [{"id": "flow", "name": "Flow"}],
            }
            if request.url.path == "/config":
                return httpx.Response(404)
            return httpx.Response(200, json=responses[request.url.path])

        client = AgnoClient("http://agent.test", transport=httpx.MockTransport(handle))
        result = asyncio.run(client.discover())
        self.assertEqual(result["version"], "3.1.0")
        self.assertEqual(result["agents"], [{"id": "helper", "name": "Helper", "type": "agent"}])
        self.assertEqual(result["workflows"][0]["id"], "flow")

    def test_auth_failure_is_not_reported_as_empty_components(self):
        def handle(request):
            return httpx.Response(401)

        client = AgnoClient("http://agent.test", transport=httpx.MockTransport(handle))
        with self.assertRaises(UpstreamError) as raised:
            asyncio.run(client.discover())
        self.assertEqual(raised.exception.status_code, 401)

    def test_reads_persisted_sessions_and_runs(self):
        def handle(request):
            self.assertEqual(request.url.params.get("type"), "workflow")
            if request.url.path == "/sessions":
                return httpx.Response(200, json={"data": [{"session_id": "s1"}], "meta": {"page": 1}})
            return httpx.Response(200, json=[{"run_id": "r1"}])

        client = AgnoClient("http://agent.test", transport=httpx.MockTransport(handle))
        self.assertEqual(asyncio.run(client.sessions("workflow"))["data"][0]["session_id"], "s1")
        self.assertEqual(asyncio.run(client.session_runs("s1", "workflow"))[0]["run_id"], "r1")


if __name__ == "__main__":
    unittest.main()
