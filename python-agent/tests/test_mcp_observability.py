from __future__ import annotations

import unittest

from opentelemetry import trace

from app.config import McpServerSettings
from app.mcp.sdk_transport import OfficialMcpTransport
from app.observability import METRICS
from tests.test_mcp_client import RecordingTransport, TestClient
from app.mcp import MCPPolicy


class McpObservabilityTest(unittest.TestCase):
    def test_base_client_records_mcp_metrics(self) -> None:
        before = METRICS.render_text().decode("utf-8")
        client = TestClient(RecordingTransport(), policy=MCPPolicy({"filter": {"embed_text"}}))

        client.call_tool("embed_text", {"text": "hello"}, agent_name="filter", run_id="mcp-metrics")

        after = METRICS.render_text().decode("utf-8")
        self.assertNotEqual(before, after)
        self.assertIn("knowmate_mcp_tool_calls_total", after)
        self.assertIn('server="embedding-mcp"', after)
        self.assertIn('tool="embed_text"', after)

    def test_http_headers_include_traceparent(self) -> None:
        transport = OfficialMcpTransport(
            {"embedding-mcp": McpServerSettings(transport="streamable_http", url="http://127.0.0.1:1/mcp")},
            timeout_seconds=1,
        )
        carrier: dict[str, str] = {}
        with trace.get_tracer(__name__).start_as_current_span("mcp-http"):
            transport._inject_trace_headers(carrier)

        self.assertIn("traceparent", carrier)
