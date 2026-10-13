import asyncio
import json
import unittest

import httpx

from agno_observability_kit.integrations.loki import recent_logs
from agno_observability_kit.integrations.prometheus import query_history


class QueryTests(unittest.TestCase):
    def test_metric_history_is_bounded_and_ignores_non_finite_samples(self):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={"status": "success", "data": {"result": [{"values": [[1, "2.5"], [2, "NaN"]]}]}})

        result = asyncio.run(query_history("http://prometheus", "sample", 2, httpx.MockTransport(handle)))
        self.assertEqual(len(requests), 3)
        self.assertEqual(result["Run rate"], [{"time": 1, "value": 2.5}])
        self.assertTrue(all(request.url.path == "/api/v1/query_range" for request in requests))
        self.assertEqual(int(requests[0].url.params["step"]), 80)
        self.assertIn('project_id="sample"', requests[0].url.params["query"])
        self.assertIn("or vector(0)", requests[1].url.params["query"])

    def test_log_query_escapes_text_and_returns_correlation_fields(self):
        seen = []

        def handle(request):
            seen.append(request.url.params)
            return httpx.Response(200, json={"status": "success", "data": {"result": [{
                "stream": {"job": "app"},
                "values": [["1700000000000000000", "failed", {"trace_id": "abc", "run_id": "run-1"}]],
            }]}})

        text = 'quote" |~ ".*'
        logs = asyncio.run(recent_logs("http://loki", "sample", hours=2, text=text, level="error", transport=httpx.MockTransport(handle)))
        self.assertEqual(logs[0]["trace_id"], "abc")
        self.assertEqual(logs[0]["run_id"], "run-1")
        self.assertEqual(logs[0]["time"], "2023-11-14T22:13:20+00:00")
        self.assertEqual(seen[0]["query"], '{project_id="sample"} |= ' + json.dumps(text) + ' |~ "(?i)error"')
        self.assertEqual(seen[0]["limit"], "50")

    def test_rejects_unknown_log_level(self):
        with self.assertRaises(ValueError):
            asyncio.run(recent_logs("http://loki", "sample", level="anything"))


if __name__ == "__main__":
    unittest.main()
