from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
from urllib import request as urlrequest

from app.config import McpServerSettings
from app.mcp import BaseMcpClient, MCPPolicy, McpToolDefinition, MemoryMcpTransport, OfficialMcpTransport
from app.mcp.milvus_client import MilvusClient
from app.mcp.neo4j_client import Neo4jClient


class RecordingTransport:
    def __init__(self, outcomes: list[object] | None = None, *, tool: McpToolDefinition | None = None) -> None:
        self.outcomes = list(outcomes or [{"ok": True}])
        self.calls = 0
        self.started = False
        self.closed = False
        self.last_payload: dict[str, object] = {}
        self.tool = tool or McpToolDefinition(
            name="embed_text",
            description="test tool",
            input_schema={
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
            },
        )

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True

    def list_tools(self, server_name: str) -> dict[str, McpToolDefinition]:
        return {self.tool.name: self.tool}

    def get_tool(self, server_name: str, tool_name: str) -> McpToolDefinition | None:
        return self.tool if tool_name == self.tool.name else None

    def call(self, server_name: str, tool_name: str, payload: dict[str, object], request_id: str) -> dict[str, object]:
        self.calls += 1
        self.last_payload = payload
        outcome = self.outcomes.pop(0) if self.outcomes else {"ok": True}
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome  # type: ignore[return-value]


class TestClient(BaseMcpClient):
    server_name = "embedding-mcp"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class McpClientTest(unittest.TestCase):
    def test_milvus_client_forwards_batch_delete_and_metadata_filter(self) -> None:
        batch_tool = McpToolDefinition(
            name="batch_insert_memory_vectors",
            description="batch",
            input_schema={"type": "object", "required": ["items"]},
            output_schema={"type": "object", "required": ["upserted_count", "ids"]},
        )
        batch_transport = RecordingTransport([{"upserted_count": 1, "ids": ["m1"]}], tool=batch_tool)
        batch_client = MilvusClient(
            batch_transport,
            policy=MCPPolicy({"memory": {"batch_insert_memory_vectors"}}),
        )

        batch_result = batch_client.batch_insert_memory_vectors(
            [{"id": "m1", "embedding": [1.0, 0.0]}],
            agent_name="memory",
            run_id="batch",
        )

        self.assertTrue(batch_result.log["success"])
        self.assertEqual(batch_transport.last_payload["items"][0]["id"], "m1")

        search_tool = McpToolDefinition(
            name="search_similar_memory",
            description="search",
            input_schema={"type": "object", "required": ["embedding"]},
            output_schema={"type": "object", "required": ["matches"]},
        )
        search_transport = RecordingTransport([{"matches": []}], tool=search_tool)
        search_client = MilvusClient(search_transport, policy=MCPPolicy({"filter": {"search_similar_memory"}}))

        search_client.search_similar_memory(
            [1.0, 0.0],
            metadata_filter={"user_id": {"eq": "u1"}},
            minimum_score=0.8,
            agent_name="filter",
            run_id="search-filter",
        )

        self.assertEqual(search_transport.last_payload["metadata_filter"], {"user_id": {"eq": "u1"}})
        self.assertEqual(search_transport.last_payload["minimum_score"], 0.8)

        delete_tool = McpToolDefinition(
            name="delete_memory_vectors",
            description="delete",
            input_schema={"type": "object"},
            output_schema={"type": "object", "required": ["deleted_count"]},
        )
        delete_transport = RecordingTransport([{"deleted_count": 1}], tool=delete_tool)
        delete_client = MilvusClient(delete_transport, policy=MCPPolicy({"memory": {"delete_memory_vectors"}}))

        delete_client.delete_memory_vectors(["m1"], agent_name="memory", run_id="delete")

        self.assertEqual(delete_transport.last_payload["ids"], ["m1"])

    def test_neo4j_client_uses_run_id_as_default_event_id(self) -> None:
        tool = McpToolDefinition(
            name="update_user_interest_graph",
            description="update",
            input_schema={"type": "object", "required": ["user_id"]},
            output_schema={"type": "object", "required": ["updated"]},
        )
        transport = RecordingTransport([{"updated": True}], tool=tool)
        client = Neo4jClient(transport, policy=MCPPolicy({"memory": {"update_user_interest_graph"}}))

        client.update_profile(
            {"user_id": "u1"},
            ["AI"],
            "positive",
            agent_name="memory",
            run_id="stable-event",
        )

        self.assertEqual(transport.last_payload["event_id"], "stable-event")

    def test_memory_transport_discovers_and_caches_tools(self) -> None:
        transport = MemoryMcpTransport()

        transport.start()
        first = transport.list_tools("embedding-mcp")
        second = transport.list_tools("embedding-mcp")

        self.assertIs(first, second)
        self.assertIn("embed_text", first)
        self.assertEqual(first["embed_text"].input_schema["required"], ["text"])

    def test_permission_denial_does_not_reach_transport(self) -> None:
        transport = RecordingTransport()
        client = TestClient(transport, policy=MCPPolicy({"summary": set()}))

        result = client.call_tool("embed_text", {"text": "hello"}, agent_name="summary", run_id="denied")

        self.assertEqual(transport.calls, 0)
        self.assertEqual(result.log["status"], "denied")

    def test_invalid_input_schema_is_rejected_before_call(self) -> None:
        transport = RecordingTransport()
        client = TestClient(transport, policy=MCPPolicy({"filter": {"embed_text"}}))

        result = client.call_tool("embed_text", {"text": 42}, agent_name="filter", run_id="schema-input")

        self.assertEqual(transport.calls, 0)
        self.assertEqual(result.result["error"]["code"], "MCP_INPUT_SCHEMA_INVALID")
        self.assertEqual(result.log["status"], "invalid_input")

    def test_invalid_output_schema_degrades_to_structured_failure(self) -> None:
        transport = RecordingTransport([{"unexpected": True}])
        client = TestClient(transport, policy=MCPPolicy({"filter": {"embed_text"}}))

        result = client.call_tool("embed_text", {"text": "hello"}, agent_name="filter", run_id="schema-output")

        self.assertEqual(result.result["error"]["code"], "MCP_OUTPUT_SCHEMA_INVALID")
        self.assertEqual(result.log["status"], "failed")

    def test_timeout_is_retried_then_succeeds(self) -> None:
        transport = RecordingTransport([TimeoutError("slow"), TimeoutError("slow"), {"ok": True}])
        client = TestClient(
            transport,
            policy=MCPPolicy({"filter": {"embed_text"}}),
            max_retries=2,
            retry_backoff_seconds=0,
        )

        result = client.call_tool("embed_text", {"text": "hello"}, agent_name="filter", run_id="retry")

        self.assertTrue(result.log["success"])
        self.assertEqual(result.log["attempts"], 3)
        self.assertEqual(transport.calls, 3)

    def test_circuit_opens_after_failure_threshold(self) -> None:
        transport = RecordingTransport([RuntimeError("down"), RuntimeError("down")])
        client = TestClient(
            transport,
            policy=MCPPolicy({"filter": {"embed_text"}}),
            max_retries=0,
            circuit_failure_threshold=2,
            circuit_reset_seconds=60,
        )

        client.call_tool("embed_text", {"text": "one"}, agent_name="filter", run_id="circuit-1")
        client.call_tool("embed_text", {"text": "two"}, agent_name="filter", run_id="circuit-2")
        result = client.call_tool("embed_text", {"text": "three"}, agent_name="filter", run_id="circuit-3")

        self.assertEqual(transport.calls, 2)
        self.assertEqual(result.result["error"]["code"], "MCP_CIRCUIT_OPEN")
        self.assertEqual(result.log["status"], "circuit_open")

    def test_memory_fallback_returns_degraded_result(self) -> None:
        primary = RecordingTransport([RuntimeError("remote down")])
        fallback = MemoryMcpTransport()
        client = TestClient(
            primary,
            policy=MCPPolicy({"filter": {"embed_text"}}),
            max_retries=0,
            fallback_transport=fallback,
        )

        result = client.call_tool("embed_text", {"text": "hello"}, agent_name="filter", run_id="fallback")

        self.assertTrue(result.log["success"])
        self.assertEqual(result.log["status"], "degraded")
        self.assertEqual(result.log["fallback"], "memory")
        self.assertIn("embedding", result.result)

    def test_open_circuit_uses_memory_fallback_without_calling_primary(self) -> None:
        primary = RecordingTransport([RuntimeError("remote down")])
        client = TestClient(
            primary,
            policy=MCPPolicy({"filter": {"embed_text"}}),
            max_retries=0,
            circuit_failure_threshold=1,
            circuit_reset_seconds=60,
            fallback_transport=MemoryMcpTransport(),
        )
        client.call_tool("embed_text", {"text": "first"}, agent_name="filter", run_id="fallback-circuit-1")

        result = client.call_tool("embed_text", {"text": "second"}, agent_name="filter", run_id="fallback-circuit-2")

        self.assertEqual(primary.calls, 1)
        self.assertTrue(result.log["success"])
        self.assertEqual(result.log["status"], "degraded")
        self.assertEqual(result.log["fallback"], "memory")

    def test_sensitive_fields_are_redacted_from_logs(self) -> None:
        tool = McpToolDefinition(
            name="embed_text",
            description="test tool",
            input_schema={"type": "object", "required": ["text", "api_key"]},
            output_schema={"type": "object", "required": ["ok"]},
        )
        transport = RecordingTransport([{"ok": True, "access_token": "response-secret"}], tool=tool)
        client = TestClient(transport, policy=MCPPolicy({"filter": {"embed_text"}}))

        result = client.call_tool(
            "embed_text",
            {"text": "hello", "api_key": "request-secret"},
            agent_name="filter",
            run_id="redact",
        )

        request_log = json.loads(result.log["request_json"])
        response_log = json.loads(result.log["response_json"])
        self.assertEqual(request_log["params"]["arguments"]["api_key"], "[REDACTED]")
        self.assertEqual(response_log["result"]["access_token"], "[REDACTED]")
        self.assertNotIn("request-secret", result.log["request_json"])
        self.assertNotIn("response-secret", result.log["response_json"])

    def test_official_stdio_transport_discovers_and_calls_tool(self) -> None:
        server = Path(__file__).resolve().parents[2] / "mcp-servers" / "embedding-mcp" / "server.py"
        transport = OfficialMcpTransport(
            {
                "embedding-mcp": McpServerSettings(
                    transport="stdio",
                    command=sys.executable,
                    args=[str(server)],
                    env={"MCP_TRANSPORT": "stdio", "EMBEDDING_MOCK_MODE": "true"},
                )
            },
            timeout_seconds=5,
        )
        try:
            transport.start()
            tools = transport.list_tools("embedding-mcp")
            result = transport.call("embedding-mcp", "embed_text", {"text": "hello"}, "stdio-call")
        finally:
            transport.close()

        self.assertIn("embed_text", tools)
        self.assertEqual(tools["embed_text"].input_schema["required"], ["text"])
        self.assertEqual(result["dim"], 8)

    def test_official_transport_can_mix_memory_and_stdio_servers(self) -> None:
        server = Path(__file__).resolve().parents[2] / "mcp-servers" / "embedding-mcp" / "server.py"
        transport = OfficialMcpTransport(
            {
                "embedding-mcp": McpServerSettings(
                    transport="stdio",
                    command=sys.executable,
                    args=[str(server)],
                    env={"MCP_TRANSPORT": "stdio", "EMBEDDING_MOCK_MODE": "true"},
                ),
                "fetch-mcp": McpServerSettings(transport="memory"),
            },
            timeout_seconds=5,
        )
        try:
            transport.start()
            embedding_tools = transport.list_tools("embedding-mcp")
            fetch_tools = transport.list_tools("fetch-mcp")
        finally:
            transport.close()

        self.assertIn("embed_text", embedding_tools)
        self.assertIn("fetch_webpage", fetch_tools)

    def test_official_streamable_http_transport_discovers_and_calls_tool(self) -> None:
        port = _free_port()
        server_dir = Path(__file__).resolve().parents[2] / "mcp-servers" / "embedding-mcp"
        env = dict(os.environ)
        env.update({"PORT": str(port), "MCP_TRANSPORT": "streamable_http", "EMBEDDING_MOCK_MODE": "true"})
        process = subprocess.Popen(
            [sys.executable, "server.py"],
            cwd=server_dir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.time() + 15
            while time.time() < deadline:
                try:
                    urlrequest.urlopen(f"http://127.0.0.1:{port}/health", timeout=1).read()
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                self.fail("Streamable HTTP MCP server did not start")

            transport = OfficialMcpTransport(
                {
                    "embedding-mcp": McpServerSettings(
                        transport="streamable_http",
                        url=f"http://127.0.0.1:{port}/mcp",
                    )
                },
                timeout_seconds=5,
            )
            try:
                transport.start()
                result = transport.call("embedding-mcp", "embed_text", {"text": "hello"}, "http-call")
            finally:
                transport.close()
        finally:
            process.terminate()
            process.wait(timeout=10)

        self.assertEqual(result["dim"], 8)

    def test_discovered_neo4j_update_schema_accepts_agent_payload(self) -> None:
        server = Path(__file__).resolve().parents[2] / "mcp-servers" / "neo4j-mcp" / "server.py"
        transport = OfficialMcpTransport(
            {
                "neo4j-mcp": McpServerSettings(
                    transport="stdio",
                    command=sys.executable,
                    args=[str(server)],
                    env={"MCP_TRANSPORT": "stdio", "NEO4J_MOCK_MODE": "true"},
                )
            },
            timeout_seconds=5,
        )
        try:
            transport.start()
            tool = transport.get_tool("neo4j-mcp", "update_user_interest_graph")
        finally:
            transport.close()

        self.assertIsNotNone(tool)
        self.assertNotIn("topics", tool.input_schema["required"])
        self.assertIn("snapshot", tool.input_schema["properties"])


if __name__ == "__main__":
    unittest.main()
