import tempfile
import unittest
from pathlib import Path

from kit.configure import render_alloy, write_config
from kit.settings import ProjectConfig


class ConfigureTests(unittest.TestCase):
    def test_optional_collectors_are_absent_until_configured(self):
        text = render_alloy(ProjectConfig())
        self.assertIn("otelcol.receiver.otlp", text)
        self.assertNotIn("prometheus.scrape", text)
        self.assertNotIn("loki.source.file", text)

    def test_rendered_collectors_have_project_labels(self):
        config = ProjectConfig(
            project_id="sample", environment="production", metrics_target="host.docker.internal:8000",
            edge_log_dir="/var/log/my-project", hub_ingest_url="http://100.64.0.10",
        )
        text = render_alloy(config)
        self.assertIn('project_id = "sample"', text)
        self.assertIn('http://100.64.0.10:9090/api/v1/write', text)
        self.assertIn('http://100.64.0.10:3100/loki/api/v1/push', text)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_config(config, root)
            self.assertEqual((root / ".runtime.env").read_text(), "HUB_BIND_IP=127.0.0.1\n")
            self.assertIn("EDGE_BIND_IP=127.0.0.1", (root / "edge/.runtime.env").read_text())
            self.assertEqual((root / "edge/generated.alloy").read_text(), text)
            self.assertEqual((root / "loadtest/.runtime.env").read_text(), 'LOCUST_TARGET_URL=""\n')


if __name__ == "__main__":
    unittest.main()
