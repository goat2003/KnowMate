import json
import logging
import unittest

from opentelemetry import trace

from app.observability import (
    JSONFormatter,
    Metrics,
    clear_run_id,
    current_run_id,
    redact_sensitive,
    set_run_id,
)


class ObservabilityTest(unittest.TestCase):
    def tearDown(self) -> None:
        clear_run_id()

    def test_redact_sensitive_masks_nested_values_and_dsn(self) -> None:
        value = {
            "headers": {
                "authorization": "Bearer secret-token",
                "cookie": "sessionid=secret-cookie",
            },
            "mysql_dsn": "mysql://user:secret-pass@localhost:3306/db",
            "log_line": "connect with user:secret-go@tcp(localhost:3306)/db",
            "nested": [
                {
                    "api_key": "secret-api-key",
                    "password": "secret-password",
                    "url": "https://example.com/?access_token=secret-access",
                }
            ],
        }

        redacted = redact_sensitive(value)
        rendered = json.dumps(redacted, sort_keys=True)

        self.assertNotIn("secret-token", rendered)
        self.assertNotIn("secret-cookie", rendered)
        self.assertNotIn("secret-pass", rendered)
        self.assertNotIn("secret-go", rendered)
        self.assertNotIn("secret-api-key", rendered)
        self.assertNotIn("secret-password", rendered)
        self.assertNotIn("secret-access", rendered)
        self.assertIn("[REDACTED]", rendered)

    def test_run_context_round_trip(self) -> None:
        self.assertIsNone(current_run_id())

        set_run_id("run-123")

        self.assertEqual(current_run_id(), "run-123")

    def test_json_formatter_includes_trace_and_run_id(self) -> None:
        set_run_id("run-json")
        formatter = JSONFormatter("python-agent")
        span = trace.NonRecordingSpan(
            trace.SpanContext(
                trace_id=0x1234567890ABCDEF1234567890ABCDEF,
                span_id=0x1234567890ABCDEF,
                is_remote=False,
                trace_flags=trace.TraceFlags(trace.TraceFlags.SAMPLED),
            )
        )

        with trace.use_span(span):
            record = logging.LogRecord(
                name="test.logger",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg="hello %s",
                args=("world",),
                exc_info=None,
            )
            payload = json.loads(formatter.format(record))

        self.assertEqual(payload["service"], "python-agent")
        self.assertEqual(payload["run_id"], "run-json")
        self.assertEqual(payload["message"], "hello world")
        self.assertRegex(payload["trace_id"], r"^[0-9a-f]{32}$")
        self.assertRegex(payload["span_id"], r"^[0-9a-f]{16}$")

    def test_metrics_render_agent_and_llm_values(self) -> None:
        metrics = Metrics(namespace="knowmate_test")

        metrics.record_agent_run("summary", "ok", 0.12)
        metrics.record_grpc_server("ProcessArticles", "OK", 0.34)
        metrics.record_llm_usage(
            provider="mock",
            model="mock-model",
            task="summary",
            status="ok",
            prompt_tokens=10,
            completion_tokens=5,
            cost_usd=0.01,
            duration_seconds=0.56,
        )

        rendered = metrics.render_text().decode("utf-8")

        self.assertIn("knowmate_test_agent_runs_total", rendered)
        self.assertIn("knowmate_test_grpc_server_duration_seconds", rendered)
        self.assertIn("knowmate_test_llm_tokens_total", rendered)
        self.assertIn("knowmate_test_llm_cost_usd_total", rendered)


if __name__ == "__main__":
    unittest.main()
