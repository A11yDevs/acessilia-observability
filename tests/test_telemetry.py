import http.server
import importlib.util
import json
import subprocess
import sys
import threading
import unittest


class TelemetryTests(unittest.TestCase):
    def test_exports_traces_metrics_and_logs_over_otlp_http(self):
        if importlib.util.find_spec("agno") is None or importlib.util.find_spec("opentelemetry.sdk") is None:
            self.skipTest("install the telemetry extra to run the OTLP export check")
        received = {}

        class Receiver(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                received[self.path] = self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *_args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        script = """
import logging
from opentelemetry import trace
from agno_observability_kit.instrumentation.agno import configure_agno_telemetry

telemetry = configure_agno_telemetry(
    service_name="test-agentos", project_id="sample", environment="test",
    collector_url=ENDPOINT, loggers=("sample.app",),
)
with trace.get_tracer("test").start_as_current_span("sample-run"):
    logging.getLogger("sample.app").warning("run complete", extra={"run_id": "run-1"})
    telemetry.record_run(component_type="agent", status="ok", duration_seconds=0.1)
assert telemetry.flush()
try:
    configure_agno_telemetry(service_name="test", project_id="sample", environment="test")
except RuntimeError as error:
    assert "already exists" in str(error)
else:
    raise AssertionError("second tracer provider was accepted")
""".replace("ENDPOINT", json.dumps(f"http://127.0.0.1:{server.server_port}"))
        try:
            result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue({"/v1/traces", "/v1/metrics", "/v1/logs"}.issubset(received), received.keys())
        from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
        from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

        traces = ExportTraceServiceRequest.FromString(received["/v1/traces"])
        metrics = ExportMetricsServiceRequest.FromString(received["/v1/metrics"])
        logs = ExportLogsServiceRequest.FromString(received["/v1/logs"])
        self.assertEqual(traces.resource_spans[0].scope_spans[0].spans[0].name, "sample-run")
        resource = {item.key: item.value.string_value for item in traces.resource_spans[0].resource.attributes}
        self.assertEqual(resource["service.name"], "test-agentos")
        self.assertEqual(resource["project_id"], "sample")
        metric_names = {item.name for scope in metrics.resource_metrics[0].scope_metrics for item in scope.metrics}
        self.assertIn("agno_runs", metric_names)
        self.assertIn("agno_run_duration_seconds", metric_names)
        record = logs.resource_logs[0].scope_logs[0].log_records[0]
        self.assertTrue(record.trace_id)
        self.assertIn("run_id", {item.key for item in record.attributes})


if __name__ == "__main__":
    unittest.main()
