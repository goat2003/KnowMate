from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FETCH_SERVER = ROOT / "fetch-mcp" / "server.py"


def load_fetch_server():
    spec = importlib.util.spec_from_file_location("fetch_mcp_server_test", FETCH_SERVER)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load fetch-mcp server")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FetchSecurityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fetch = load_fetch_server()

    def assert_blocked(self, url: str) -> None:
        with self.assertRaises(self.fetch.ToolError):
            self.fetch._valid_url(url)

    def test_blocks_loopback_private_and_metadata_addresses(self) -> None:
        for url in [
            "http://127.0.0.1/",
            "http://localhost/",
            "http://10.0.0.5/",
            "http://172.16.0.2/",
            "http://192.168.1.10/",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/",
            "http://metadata.google.internal/computeMetadata/v1/",
        ]:
            with self.subTest(url=url):
                self.assert_blocked(url)

    def test_blocks_dns_names_that_resolve_to_private_ips(self) -> None:
        with mock.patch.object(self.fetch.socket, "getaddrinfo") as getaddrinfo:
            getaddrinfo.return_value = [(self.fetch.socket.AF_INET, 0, 0, "", ("127.0.0.1", 80))]
            self.assert_blocked("https://public-name.example/")

    def test_rejects_userinfo_and_non_http_schemes(self) -> None:
        self.assert_blocked("file:///etc/passwd")
        self.assert_blocked("https://user:pass@example.com/")


if __name__ == "__main__":
    unittest.main()
