import tempfile
import unittest
from pathlib import Path

from agno_observability_kit.alloy import render_alloy
from agno_observability_kit.configure import write_config
from agno_observability_kit.settings import ProjectConfig


class ConfigureTests(unittest.TestCase):
    def test_optional_collectors_are_absent_until_configured(self):
        text = render_alloy(ProjectConfig())
        self.assertIn("otelcol.receiver.otlp", text)
        self.assertIn("metrics = [otelcol.exporter.prometheus.server.input]", text)
        self.assertIn("logs = [otelcol.exporter.loki.server.input]", text)
        self.assertIn('external_labels = { project_id = "example", environment = "local" }', text)
        self.assertNotIn("prometheus.scrape", text)
        self.assertNotIn("loki.source.file", text)
        self.assertNotIn('otelcol.exporter.otlphttp "langfuse"', text)

    def test_rendered_collectors_have_project_labels(self):
        config = ProjectConfig(
            project_id="sample", environment="production", metrics_target="host.docker.internal:8000",
            collector_log_dir="/var/log/my-project", observability_ingest_url="http://100.64.0.10",
        )
        text = render_alloy(config)
        self.assertIn('project_id = "sample"', text)
        self.assertIn('http://100.64.0.10:9090/api/v1/write', text)
        self.assertIn('http://100.64.0.10:3100/loki/api/v1/push', text)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_config(config, root)
            self.assertIn("OBSERVABILITY_BIND_IP=127.0.0.1", (root / "infra/observability-server/.runtime.env").read_text())
            self.assertIn("LANGFUSE_UI_PORT=3001", (root / "infra/observability-server/.runtime.env").read_text())
            self.assertIn('LANGFUSE_MEDIA_URL="http://localhost:9092"', (root / "infra/observability-server/.runtime.env").read_text())
            self.assertIn("COLLECTOR_BIND_IP=127.0.0.1", (root / "infra/application-collector/.runtime.env").read_text())
            self.assertEqual((root / "infra/application-collector/generated.alloy").read_text(), text)
            self.assertEqual((root / "infra/performance-tests/.runtime.env").read_text(), 'LOCUST_TARGET_URL=""\n')

    def test_langfuse_fanout_uses_runtime_credentials(self):
        config = ProjectConfig(langfuse_otlp_url="https://trace.example/api/public/otel")
        text = render_alloy(config)
        self.assertIn("otelcol.exporter.otlphttp.langfuse.input", text)
        self.assertIn('endpoint = "https://trace.example/api/public/otel"', text)
        self.assertIn('sys.env("LANGFUSE_PUBLIC_KEY")', text)
        self.assertIn('  username = sys.env("LANGFUSE_PUBLIC_KEY")', text)
        self.assertNotIn("client_auth", text)
        self.assertIn('"x-langfuse-ingestion-version" = "4"', text)
        self.assertNotIn("pk-lf-", text)

    def test_default_log_mount_does_not_embed_checkout_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_config(ProjectConfig(), root)
            collector = root / "infra/application-collector"
            runtime = (collector / ".runtime.env").read_text()
            self.assertIn('COLLECTOR_LOG_DIR="./logs"', runtime)
            self.assertNotIn(str(root), runtime)
            self.assertTrue((collector / "logs").is_dir())


if __name__ == "__main__":
    unittest.main()
