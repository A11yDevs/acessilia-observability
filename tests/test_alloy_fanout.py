import base64
import gzip
import http.server
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from uuid import uuid4

import httpx

from agno_observability_kit.alloy import render_alloy
from agno_observability_kit.settings import ProjectConfig


@unittest.skipUnless(os.getenv("RUN_DOCKER_INTEGRATION") == "1", "set RUN_DOCKER_INTEGRATION=1 for the Alloy fan-out check")
class AlloyFanoutTests(unittest.TestCase):
    def test_tempo_still_receives_traces_when_langfuse_fails(self):
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

        gateway = subprocess.check_output(
            ["docker", "network", "inspect", "bridge", "--format", "{{(index .IPAM.Config 0).Gateway}}"], text=True,
        ).strip()
        received = {"tempo": [], "langfuse": []}
        langfuse_status = [200]

        def receiver(name):
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_POST(self):
                    body = self.rfile.read(int(self.headers["Content-Length"]))
                    received[name].append((self.path, {key.lower(): value for key, value in self.headers.items()}, body))
                    self.send_response(langfuse_status[0] if name == "langfuse" else 200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b"{}")

                def log_message(self, *_args):
                    pass

            return Handler

        def trace_ids(name: str) -> set[str]:
            ids = set()
            for _, headers, body in received[name]:
                if headers.get("content-encoding") == "gzip":
                    body = gzip.decompress(body)
                request = ExportTraceServiceRequest.FromString(body)
                for resource in request.resource_spans:
                    for scope in resource.scope_spans:
                        ids.update(span.trace_id.hex() for span in scope.spans)
            return ids

        try:
            tempo = http.server.ThreadingHTTPServer((gateway, 4318), receiver("tempo"))
        except OSError as exc:
            self.skipTest(f"cannot bind the Docker bridge on port 4318: {exc}")
        langfuse = http.server.ThreadingHTTPServer((gateway, 0), receiver("langfuse"))
        threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (tempo, langfuse)]
        for thread in threads:
            thread.start()

        container = "agno-kit-fanout-" + uuid4().hex[:10]
        with tempfile.TemporaryDirectory() as directory:
            config = ProjectConfig(
                observability_ingest_url="http://host.docker.internal",
                langfuse_otlp_url=f"http://host.docker.internal:{langfuse.server_port}/api/public/otel",
            )
            config_path = Path(directory) / "config.alloy"
            config_path.write_text(render_alloy(config))
            try:
                subprocess.run([
                    "docker", "run", "--rm", "-d", "--name", container,
                    "--add-host", "host.docker.internal:host-gateway",
                    "-p", "127.0.0.1::4318",
                    "-e", "LANGFUSE_PUBLIC_KEY=public-test",
                    "-e", "LANGFUSE_SECRET_KEY=secret-test",
                    "-v", f"{config_path}:/etc/alloy/config.alloy:ro",
                    "grafana/alloy:v1.18.1", "run", "/etc/alloy/config.alloy",
                ], check=True, capture_output=True, text=True)
                mapping = subprocess.check_output(["docker", "port", container, "4318/tcp"], text=True).strip()
                collector_url = f"http://127.0.0.1:{mapping.rsplit(':', 1)[1]}/v1/traces"

                def send_trace() -> None:
                    request = ExportTraceServiceRequest()
                    span = request.resource_spans.add().scope_spans.add().spans.add()
                    span.trace_id = uuid4().bytes
                    span.span_id = uuid4().bytes[:8]
                    span.name = "fanout-smoke"
                    span.start_time_unix_nano = time.time_ns()
                    span.end_time_unix_nano = span.start_time_unix_nano + 1_000_000
                    for _ in range(30):
                        try:
                            response = httpx.post(collector_url, content=request.SerializeToString(), headers={"Content-Type": "application/x-protobuf"}, timeout=2)
                            response.raise_for_status()
                            return
                        except (httpx.HTTPError, OSError):
                            time.sleep(0.2)
                    self.fail("Alloy OTLP receiver did not start")

                def await_delivery(name: str, count: int) -> None:
                    deadline = time.monotonic() + 15
                    while len(received[name]) < count and time.monotonic() < deadline:
                        time.sleep(0.1)
                    self.assertGreaterEqual(len(received[name]), count, received)

                send_trace()
                await_delivery("tempo", 1)
                await_delivery("langfuse", 1)
                self.assertEqual(trace_ids("tempo"), trace_ids("langfuse"))
                path, headers, _ = received["langfuse"][0]
                self.assertEqual(path, "/api/public/otel/v1/traces")
                self.assertEqual(headers["authorization"], "Basic " + base64.b64encode(b"public-test:secret-test").decode())
                self.assertEqual(headers["x-langfuse-ingestion-version"], "4")

                smoke = subprocess.run(
                    [sys.executable, "-m", "agno_observability_kit.smoke_trace", "--collector-url", collector_url.removesuffix("/v1/traces")],
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(smoke.returncode, 0, smoke.stderr)
                self.assertIn("Trace ID:", smoke.stdout)
                await_delivery("tempo", 2)
                await_delivery("langfuse", 2)
                smoke_trace_id = smoke.stdout.split("Trace ID: ", 1)[1].splitlines()[0]
                self.assertIn(smoke_trace_id, trace_ids("tempo"))
                self.assertIn(smoke_trace_id, trace_ids("langfuse"))

                langfuse_status[0] = 503
                send_trace()
                await_delivery("tempo", 3)
                await_delivery("langfuse", 3)
            finally:
                subprocess.run(["docker", "stop", "-t", "2", container], capture_output=True, timeout=10)
                for server in (tempo, langfuse):
                    server.shutdown()
                    server.server_close()
                for thread in threads:
                    thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
