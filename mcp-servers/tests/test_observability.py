from __future__ import annotations

import unittest

from common.observability import Metrics, extract_trace_context, redact_sensitive
from common.simple_http_mcp import ToolError, ToolSpec, create_server


class McpServerObservabilityTest(unittest.TestCase):
    def test_redact_sensitive_masks_headers(self) -> None:
        encoded = str(redact_sensitive({"authorization": "Bearer server-secret"}))

        self.assertNotIn("server-secret", encoded)

    def test_metrics_render_tool_call(self) -> None:
        metrics = Metrics(namespace="knowmate_test_mcp")
        metrics.record_tool_call("embedding-mcp", "embed_text", "success", 0.1)

        text = metrics.render_text().decode("utf-8")
        self.assertIn("knowmate_test_mcp_mcp_tool_calls_total", text)
        self.assertIn('tool="embed_text"', text)

    def test_create_server_registers_metrics_route(self) -> None:
        server = create_server(
            "test-mcp",
            7999,
            [ToolSpec(name="echo", description="echo", input_schema={"type": "object"}, output_schema={}, examples=[])],
            lambda name, payload: {"ok": True},
        )

        paths = {getattr(route, "path", "") for route in server._custom_starlette_routes}
        self.assertIn("/metrics", paths)
