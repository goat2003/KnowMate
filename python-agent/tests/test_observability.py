import json
import logging
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from opentelemetry import trace

from app import observability
from app.observability import (
    JSONFormatter,
    Metrics,
    clear_run_id,
    current_run_id,
    redact_sensitive,
    set_run_id,
)


class ObservabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self._root_handlers = logging.getLogger().handlers[:]
        self._root_level = logging.getLogger().level
        self._grpc_instrumented = observability._grpc_instrumented
        self._tracing_configured = observability._tracing_configured

    def tearDown(self) -> None:
        clear_run_id()
        observability._grpc_instrumented = self._grpc_instrumented
        observability._tracing_configured = self._tracing_configured
        root = logging.getLogger()
        root.handlers = self._root_handlers
        root.setLevel(self._root_level)

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

    def test_redact_sensitive_masks_common_header_and_basic_auth_shapes(self) -> None:
        value = {
            "X-API-Key": "secret-x-key",
            "Proxy-Authorization": "Basic c2VjcmV0LXByb3h5",
            "client_secret": "secret-client",
            "headers": [
                ("X-API-Key", "secret-pair"),
                ("set-cookie", "sid=secret-set-cookie"),
                ("safe", "Basic c2VjcmV0LWJhc2lj"),
            ],
        }

        redacted = redact_sensitive(value)
        rendered = json.dumps(redacted, sort_keys=True)

        self.assertNotIn("secret-x-key", rendered)
        self.assertNotIn("c2VjcmV0LXByb3h5", rendered)
        self.assertNotIn("secret-client", rendered)
        self.assertNotIn("secret-pair", rendered)
        self.assertNotIn("secret-set-cookie", rendered)
        self.assertNotIn("c2VjcmV0LWJhc2lj", rendered)
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

    def test_json_formatter_handles_non_json_payload(self) -> None:
        formatter = JSONFormatter("python-agent")
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="payload",
            args=(),
            exc_info=None,
        )
        record.payload = {
            "items": {"a"},
            "raw": b"token=secret-byte",
            "time": datetime(2026, 6, 8, tzinfo=timezone.utc),
            "error": ValueError("password=secret-error"),
        }

        payload = json.loads(formatter.format(record))
        rendered = json.dumps(payload, sort_keys=True)

        self.assertEqual(payload["message"], "payload")
        self.assertIn("items", payload["payload"])
        self.assertIn("raw", payload["payload"])
        self.assertIn("time", payload["payload"])
        self.assertIn("error", payload["payload"])
        self.assertNotIn("secret-byte", rendered)
        self.assertNotIn("secret-error", rendered)

    def test_init_observability_otel_disabled_is_idempotent(self) -> None:
        observability._grpc_instrumented = False
        observability._tracing_configured = False
        instrumentor = Mock()

        with (
            patch.dict("os.environ", {"OTEL_ENABLED": "false"}, clear=False),
            patch.object(observability, "GrpcInstrumentorServer", return_value=instrumentor) as instrumentor_cls,
            patch.object(observability, "OTLPSpanExporter") as exporter_cls,
            patch.object(observability, "TracerProvider") as provider_cls,
        ):
            observability.init_observability("python-agent")
            observability.init_observability("python-agent")

        self.assertEqual(instrumentor_cls.call_count, 1)
        instrumentor.instrument.assert_called_once_with()
        exporter_cls.assert_not_called()
        provider_cls.assert_not_called()
        self.assertFalse(observability._tracing_configured)

    def test_init_observability_existing_provider_skips_exporter_allocation(self) -> None:
        observability._grpc_instrumented = True
        observability._tracing_configured = False
        existing_provider = object()

        with (
            patch.dict("os.environ", {"OTEL_ENABLED": "true"}, clear=False),
            patch.object(observability.trace, "get_tracer_provider", return_value=existing_provider),
            patch.object(observability.trace, "set_tracer_provider") as set_provider,
            patch.object(observability, "OTLPSpanExporter") as exporter_cls,
            patch.object(observability, "TracerProvider") as provider_cls,
            patch.object(observability, "BatchSpanProcessor") as processor_cls,
        ):
            observability.init_observability("python-agent")

        exporter_cls.assert_not_called()
        provider_cls.assert_not_called()
        processor_cls.assert_not_called()
        set_provider.assert_not_called()
        self.assertTrue(observability._tracing_configured)

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
