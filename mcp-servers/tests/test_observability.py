from __future__ import annotations

import asyncio
import json
import logging
import unittest
from unittest.mock import Mock, patch

from opentelemetry import trace
from opentelemetry.trace import ProxyTracerProvider

from common import observability
from common.observability import (
    JSONFormatter,
    METRICS,
    Metrics,
    current_trace_context,
    extract_trace_context,
    init_observability,
    record_tool,
    redact_sensitive,
    reset_current_http_headers,
    set_current_http_headers,
)
from common.simple_http_mcp import ToolError, ToolSpec, _install_trace_header_capture, create_server


class McpServerObservabilityTest(unittest.TestCase):
    def test_redact_sensitive_masks_headers(self) -> None:
        encoded = str(redact_sensitive({"authorization": "Bearer server-secret"}))

        self.assertNotIn("server-secret", encoded)

    def test_redact_sensitive_masks_dsn_passwords(self) -> None:
        encoded = str(
            redact_sensitive(
                {
                    "url": "mysql://user:url-secret@localhost/db",
                    "go": "user:go-secret@tcp(localhost:3306)/db",
                    "basic": "Basic basic-secret",
                    "token": "api_key=key-secret",
                }
            )
        )

        self.assertNotIn("url-secret", encoded)
        self.assertNotIn("go-secret", encoded)
        self.assertNotIn("basic-secret", encoded)
        self.assertNotIn("key-secret", encoded)

    def test_metrics_render_tool_call(self) -> None:
        metrics = Metrics(namespace="knowmate_test_mcp")
        metrics.record_tool_call("embedding-mcp", "embed_text", "success", 0.1)

        text = metrics.render_text().decode("utf-8")
        self.assertIn("knowmate_test_mcp_mcp_tool_calls_total", text)
        self.assertIn('tool="embed_text"', text)

    def test_record_tool_records_success_for_sync_handler(self) -> None:
        before = METRICS.render_text().decode("utf-8")

        result = asyncio.run(record_tool("embedding-mcp", "embed_text", lambda: {"ok": True}))

        after = METRICS.render_text().decode("utf-8")
        self.assertEqual({"ok": True}, result)
        self.assertNotEqual(before, after)
        self.assertIn('server="embedding-mcp"', after)
        self.assertIn('tool="embed_text"', after)
        self.assertIn('status="success"', after)

    def test_record_tool_awaits_async_handler_and_records_failure(self) -> None:
        async def failing_handler() -> dict[str, bool]:
            await asyncio.sleep(0)
            raise ToolError("boom")

        with self.assertRaises(ToolError):
            asyncio.run(record_tool("embedding-mcp", "embed_text", failing_handler))

        text = METRICS.render_text().decode("utf-8")
        self.assertIn('server="embedding-mcp"', text)
        self.assertIn('tool="embed_text"', text)
        self.assertIn('status="failed"', text)
        self.assertIn("knowmate_mcp_tool_failures_total", text)

    def test_extract_trace_context_accepts_traceparent(self) -> None:
        context = extract_trace_context(
            {"traceparent": "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01"}
        )

        span_context = trace.get_current_span(context).get_span_context()
        self.assertTrue(span_context.is_valid)
        self.assertEqual(span_context.trace_id, 0x1234567890ABCDEF1234567890ABCDEF)
        self.assertEqual(span_context.span_id, 0x1234567890ABCDEF)

    def test_current_trace_context_uses_captured_http_headers(self) -> None:
        token = set_current_http_headers(
            {"traceparent": "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01"}
        )
        try:
            span_context = trace.get_current_span(current_trace_context()).get_span_context()
        finally:
            reset_current_http_headers(token)

        self.assertTrue(span_context.is_valid)
        self.assertEqual(span_context.trace_id, 0x1234567890ABCDEF1234567890ABCDEF)

    def test_record_tool_uses_extracted_parent_context(self) -> None:
        context = extract_trace_context(
            {"traceparent": "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01"}
        )

        result = asyncio.run(record_tool("embedding-mcp", "embed_text", lambda: {"ok": True}, context=context))

        self.assertEqual({"ok": True}, result)
        self.assertEqual(
            trace.get_current_span(context).get_span_context().trace_id,
            0x1234567890ABCDEF1234567890ABCDEF,
        )

    def test_json_formatter_masks_sensitive_values(self) -> None:
        formatter = JSONFormatter("mcp-test")
        record = logging.LogRecord(
            name="mcp",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="authorization=Bearer secret-token",
            args=(),
            exc_info=None,
        )

        payload = json.loads(formatter.format(record))

        self.assertEqual(payload["service"], "mcp-test")
        self.assertNotIn("secret-token", json.dumps(payload))

    def test_init_observability_configures_json_logging_when_otel_disabled(self) -> None:
        with patch.dict("os.environ", {"OTEL_ENABLED": "false"}, clear=False):
            init_observability("mcp-test")

        self.assertTrue(logging.getLogger().handlers)
        self.assertIsInstance(logging.getLogger().handlers[0].formatter, JSONFormatter)

    def test_init_observability_configures_tracer_provider(self) -> None:
        previous_configured = observability._tracing_configured
        self.addCleanup(lambda: setattr(observability, "_tracing_configured", previous_configured))

        observability._tracing_configured = False
        provider = Mock()
        with (
            patch.dict("os.environ", {"OTEL_ENABLED": "true", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317"}, clear=False),
            patch.object(observability.trace, "get_tracer_provider", return_value=ProxyTracerProvider()),
            patch.object(observability.trace, "set_tracer_provider") as set_provider,
            patch.object(observability, "OTLPSpanExporter") as exporter_cls,
            patch.object(observability, "TracerProvider", return_value=provider) as provider_cls,
            patch.object(observability, "BatchSpanProcessor") as processor_cls,
        ):
            init_observability("mcp-test")

        exporter_cls.assert_called_once_with(endpoint="http://collector:4317")
        provider_cls.assert_called_once()
        processor_cls.assert_called_once_with(exporter_cls.return_value)
        provider.add_span_processor.assert_called_once_with(processor_cls.return_value)
        set_provider.assert_called_once_with(provider)

    def test_create_server_registers_metrics_route(self) -> None:
        server = create_server(
            "test-mcp",
            7999,
            [ToolSpec(name="echo", description="echo", input_schema={"type": "object"}, output_schema={}, examples=[])],
            lambda name, payload: {"ok": True},
        )

        paths = {getattr(route, "path", "") for route in server._custom_starlette_routes}
        self.assertIn("/metrics", paths)

    def test_trace_header_capture_wraps_streamable_http_app(self) -> None:
        captured_trace_ids: list[int] = []

        class FakeServer:
            def streamable_http_app(self):
                async def app(_scope, _receive, send):
                    captured_trace_ids.append(trace.get_current_span(current_trace_context()).get_span_context().trace_id)
                    await send({"type": "http.response.start", "status": 200, "headers": []})
                    await send({"type": "http.response.body", "body": b""})

                return app

        server = FakeServer()
        _install_trace_header_capture(server)
        app = server.streamable_http_app()

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(_message):
            return None

        asyncio.run(
            app(
                {
                    "type": "http",
                    "headers": [
                        (b"traceparent", b"00-1234567890abcdef1234567890abcdef-1234567890abcdef-01")
                    ],
                },
                receive,
                send,
            )
        )

        self.assertEqual(captured_trace_ids, [0x1234567890ABCDEF1234567890ABCDEF])
