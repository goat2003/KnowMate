from __future__ import annotations

import asyncio
import unittest

from common.observability import METRICS, Metrics, extract_trace_context, record_tool, redact_sensitive
from common.simple_http_mcp import ToolError, ToolSpec, create_server


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

        self.assertIsNotNone(context)

    def test_create_server_registers_metrics_route(self) -> None:
        server = create_server(
            "test-mcp",
            7999,
            [ToolSpec(name="echo", description="echo", input_schema={"type": "object"}, output_schema={}, examples=[])],
            lambda name, payload: {"ok": True},
        )

        paths = {getattr(route, "path", "") for route in server._custom_starlette_routes}
        self.assertIn("/metrics", paths)
