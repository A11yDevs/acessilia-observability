import asyncio
import unittest
from unittest.mock import patch

import httpx

from agno_observability_kit.settings import ProjectConfig
from agno_observability_kit.status import source_status


class SourceStatusTests(unittest.TestCase):
    def test_collector_heartbeat_and_langfuse_exporter_states(self):
        values = {"up": 1, "sent": 3, "failed": 0, "queued": 0}

        def response(request):
            if request.url.host == "prometheus":
                query = request.url.params["query"]
                if query.startswith("up{"):
                    value = values["up"]
                elif "sent_spans_total" in query:
                    value = values["sent"]
                elif "send_failed_spans_total" in query:
                    value = values["failed"]
                elif "queue_size" in query:
                    value = values["queued"]
                else:
                    value = None
                result = [] if value is None else [{"value": [1, str(value)]}]
                return httpx.Response(200, json={"status": "success", "data": {"result": result}})
            if request.url.host == "loki":
                return httpx.Response(200, json={"status": "success", "data": {"result": []}})
            return httpx.Response(200, json={"traces": []})

        transport = httpx.MockTransport(response)
        client_type = httpx.AsyncClient

        def client(*args, **kwargs):
            return client_type(*args, transport=transport, **kwargs)

        config = ProjectConfig(langfuse_otlp_url="https://traces.example/api/public/otel")
        with patch("agno_observability_kit.status.httpx.AsyncClient", side_effect=client):
            healthy = asyncio.run(source_status(config))
            values.update(up=0, failed=2, queued=1)
            degraded = asyncio.run(source_status(config))

        self.assertEqual(healthy["collector"]["state"], "connected")
        self.assertEqual(healthy["langfuse"]["state"], "delivered")
        self.assertEqual(degraded["collector"]["state"], "unavailable")
        self.assertEqual(degraded["langfuse"]["state"], "degraded")
        self.assertIn("2 spans in failed exports", degraded["langfuse"]["detail"])


if __name__ == "__main__":
    unittest.main()
