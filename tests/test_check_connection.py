import asyncio
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agno_observability_kit.check_connection import _tcp, application_checks, server_checks
from agno_observability_kit.settings import ProjectConfig


class ConnectionChecksTests(unittest.TestCase):
    def test_tcp_check_distinguishes_reachable_and_refused_ports(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        try:
            self.assertTrue(_tcp("local", "127.0.0.1", port)[1])
        finally:
            listener.close()
        self.assertFalse(_tcp("local", "127.0.0.1", port)[1])

    def test_application_checks_require_langfuse_keys_only_when_enabled(self):
        with tempfile.TemporaryDirectory() as directory, patch("agno_observability_kit.check_connection._tcp", return_value=("network", True, "reachable")):
            root = Path(directory)
            config = ProjectConfig(langfuse_otlp_url="https://traces.example/api/public/otel")
            checks = application_checks(config, root)
            self.assertEqual(checks[-1], ("Langfuse credentials", False, "set both keys in infra/application-collector/.env"))
            credentials = root / "infra/application-collector/.env"
            credentials.parent.mkdir(parents=True)
            credentials.write_text("LANGFUSE_PUBLIC_KEY=public\nLANGFUSE_SECRET_KEY=secret\n")
            self.assertTrue(application_checks(config, root)[-1][1])
            self.assertEqual(len(application_checks(ProjectConfig(), root)), 4)

    def test_server_check_reports_missing_agentos_url(self):
        with patch("agno_observability_kit.check_connection._tcp", return_value=("network", True, "reachable")):
            checks = asyncio.run(server_checks(ProjectConfig()))
        self.assertEqual(checks[0], ("AgentOS", False, "set agentos_url in config.py"))


if __name__ == "__main__":
    unittest.main()
