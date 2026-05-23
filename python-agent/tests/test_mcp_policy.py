import unittest

from app.mcp import EmbeddingClient, FetchClient, MCPPolicy, MockMcpTransport


class MCPPolicyTest(unittest.TestCase):
    def test_authorized_call_records_context(self) -> None:
        client = EmbeddingClient(MockMcpTransport(), policy=MCPPolicy())

        result = client.embed_text("hello", agent_name="filter", run_id="run-policy")

        self.assertTrue(result.log["success"])
        self.assertEqual(result.log["status"], "success")
        self.assertEqual(result.log["run_id"], "run-policy")
        self.assertEqual(result.log["agent_name"], "filter")
        self.assertEqual(result.log["server_name"], "embedding-mcp")
        self.assertEqual(result.log["tool_name"], "embed_text")
        self.assertIn("embedding", result.result)

    def test_unauthorized_call_is_denied_and_logged(self) -> None:
        client = FetchClient(MockMcpTransport(), policy=MCPPolicy())

        result = client.fetch_url("https://example.com", agent_name="filter", run_id="run-denied")

        self.assertFalse(result.log["success"])
        self.assertEqual(result.log["status"], "denied")
        self.assertEqual(result.log["run_id"], "run-denied")
        self.assertEqual(result.log["agent_name"], "filter")
        self.assertIn("cannot call tool", result.log["error_message"])
        self.assertEqual(result.result["error"]["code"], "MCP_PERMISSION_DENIED")


if __name__ == "__main__":
    unittest.main()
