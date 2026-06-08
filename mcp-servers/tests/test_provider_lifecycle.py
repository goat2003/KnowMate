from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


COMMON = Path(__file__).resolve().parents[1] / "common"
sys.path.insert(0, str(COMMON))

from provider import ManagedProvider, ProviderUnavailableError, read_secret  # noqa: E402
from simple_http_mcp import build_health_payload  # noqa: E402


class FakeProvider:
    def __init__(self, *, fail_initialize: bool = False) -> None:
        self.fail_initialize = fail_initialize
        self.closed = False

    def initialize(self) -> None:
        if self.fail_initialize:
            raise RuntimeError("dependency down")

    def health(self) -> dict[str, object]:
        return {"dependency": "fake", "dimension": 3}

    def close(self) -> None:
        self.closed = True


class ProviderLifecycleTest(unittest.TestCase):
    def test_read_secret_prefers_environment_then_secret_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            secret_path = Path(directory) / "secret.txt"
            secret_path.write_text("file-secret\n", encoding="utf-8")

            from_file = read_secret("MISSING_TEST_SECRET", str(secret_path))
            from_environment = read_secret("PATH", str(secret_path))

        self.assertEqual(from_file, "file-secret")
        self.assertNotEqual(from_environment, "file-secret")

    def test_initialization_failure_is_captured_without_raising(self) -> None:
        provider = FakeProvider(fail_initialize=True)
        managed = ManagedProvider(lambda: provider, mode="production")

        managed.initialize()

        self.assertFalse(managed.ready)
        self.assertTrue(provider.closed)
        self.assertIn("dependency down", managed.health()["error"])
        with self.assertRaises(ProviderUnavailableError):
            managed.get()

    def test_memory_provider_reports_healthy_and_closes(self) -> None:
        provider = FakeProvider()
        managed = ManagedProvider(lambda: provider, mode="memory")

        managed.initialize()
        health = managed.health()
        managed.close()

        self.assertTrue(health["ready"])
        self.assertTrue(provider.closed)
        self.assertEqual(health["details"]["dimension"], 3)

    def test_health_payload_uses_dynamic_dependency_status(self) -> None:
        managed = ManagedProvider(lambda: FakeProvider(fail_initialize=True), mode="production")
        managed.initialize()

        payload, status_code = build_health_payload(
            "test-mcp",
            "streamable-http",
            {"mode": "production"},
            managed.health,
        )

        self.assertEqual(status_code, 503)
        self.assertEqual(payload["status"], "unhealthy")
        self.assertIn("dependency down", payload["dependency"]["error"])


if __name__ == "__main__":
    unittest.main()
