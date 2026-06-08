from __future__ import annotations

import asyncio
import unittest

from opentelemetry import trace
from opentelemetry.context import attach, detach
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, TraceState, set_span_in_context

from app.config import McpServerSettings
from app.mcp import MCPPolicy
from app.mcp.sdk_transport import OfficialMcpTransport
from app.observability import METRICS
from tests.test_mcp_client import RecordingTransport, TestClient


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

    def test_http_headers_do_not_include_fake_traceparent_without_valid_span(self) -> None:
        transport = OfficialMcpTransport(
            {"embedding-mcp": McpServerSettings(transport="streamable_http", url="http://127.0.0.1:1/mcp")},
            timeout_seconds=1,
        )
        carrier: dict[str, str] = {}

        transport._inject_trace_headers(carrier)

        self.assertNotIn("traceparent", carrier)

    def test_http_headers_include_traceparent_for_valid_sampled_span(self) -> None:
        transport = OfficialMcpTransport(
            {"embedding-mcp": McpServerSettings(transport="streamable_http", url="http://127.0.0.1:1/mcp")},
            timeout_seconds=1,
        )
        carrier: dict[str, str] = {}
        span_context = SpanContext(
            trace_id=0x1234567890ABCDEF1234567890ABCDEF,
            span_id=0x1234567890ABCDEF,
            is_remote=False,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
            trace_state=TraceState(),
        )
        context = set_span_in_context(NonRecordingSpan(span_context))

        transport._inject_trace_headers(carrier, context=context)

        self.assertEqual(
            carrier["traceparent"],
            "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01",
        )

    def test_http_headers_include_current_context_traceparent(self) -> None:
        transport = OfficialMcpTransport(
            {"embedding-mcp": McpServerSettings(transport="streamable_http", url="http://127.0.0.1:1/mcp")},
            timeout_seconds=1,
        )
        carrier: dict[str, str] = {}
        span_context = SpanContext(
            trace_id=0xABCDEF1234567890ABCDEF1234567890,
            span_id=0xABCDEF1234567890,
            is_remote=False,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
            trace_state=TraceState(),
        )
        token = attach(set_span_in_context(NonRecordingSpan(span_context)))
        try:
            with trace.get_tracer(__name__).start_as_current_span("mcp-http"):
                transport._inject_trace_headers(carrier)
        finally:
            detach(token)

        self.assertIn("traceparent", carrier)

    def test_streamable_http_request_hook_uses_attached_context(self) -> None:
        transport = OfficialMcpTransport(
            {"embedding-mcp": McpServerSettings(transport="streamable_http", url="http://127.0.0.1:1/mcp")},
            timeout_seconds=1,
        )
        config = McpServerSettings(
            transport="streamable_http",
            url="http://127.0.0.1:1/mcp",
            headers={"x-static": "kept"},
        )
        span_context = SpanContext(
            trace_id=0xFEDCBA0987654321FEDCBA0987654321,
            span_id=0xFEDCBA0987654321,
            is_remote=False,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
            trace_state=TraceState(),
        )
        token = attach(set_span_in_context(NonRecordingSpan(span_context)))
        try:
            client = transport._create_streamable_http_client(config, inject_trace_context=True)
            request = client.build_request("POST", "http://127.0.0.1:1/mcp")
            for hook in client.event_hooks["request"]:
                asyncio.run(hook(request))
            asyncio.run(client.aclose())
        finally:
            detach(token)

        self.assertEqual(request.headers["x-static"], "kept")
        self.assertEqual(
            request.headers["traceparent"],
            "00-fedcba0987654321fedcba0987654321-fedcba0987654321-01",
        )
