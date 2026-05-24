# 文件作用：
# 本文件测试 MCP Client 的权限控制和日志记录行为。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的测试层，覆盖 app/mcp/policy.py 和 BaseMcpClient.call_tool。
#
# 主要内容：
# 1. 授权调用：验证成功日志包含 run_id、agent_name、server_name、tool_name。
# 2. 未授权调用：验证越权工具被 denied，并返回 MCP_PERMISSION_DENIED。
#
# 初学者阅读建议：
# 先读 app/mcp/policy.py 中的 DEFAULT_AGENT_TOOL_PERMISSIONS，再看这些测试如何验证白名单生效。
import unittest

from app.mcp import EmbeddingClient, FetchClient, MCPPolicy, MockMcpTransport


# 类作用：
# MCPPolicyTest 验证 MCP 权限和日志数据结构。
class MCPPolicyTest(unittest.TestCase):
    # 函数作用：
    # 验证 filter Agent 调用 embed_text 是授权行为，并记录成功日志。
    def test_authorized_call_records_context(self) -> None:
        # 使用 MockMcpTransport，避免测试依赖真实 MCP HTTP Server。
        client = EmbeddingClient(MockMcpTransport(), policy=MCPPolicy())

        # filter Agent 默认允许调用 embed_text。
        result = client.embed_text("hello", agent_name="filter", run_id="run-policy")

        # 断言日志字段完整且状态为 success。
        self.assertTrue(result.log["success"])
        self.assertEqual(result.log["status"], "success")
        self.assertEqual(result.log["run_id"], "run-policy")
        self.assertEqual(result.log["agent_name"], "filter")
        self.assertEqual(result.log["server_name"], "embedding-mcp")
        self.assertEqual(result.log["tool_name"], "embed_text")
        self.assertIn("embedding", result.result)

    # 函数作用：
    # 验证 filter Agent 调用 fetch_webpage 会被权限策略拒绝。
    def test_unauthorized_call_is_denied_and_logged(self) -> None:
        # FetchClient 对应 fetch-mcp，但 filter Agent 默认没有 fetch_webpage 权限。
        client = FetchClient(MockMcpTransport(), policy=MCPPolicy())

        result = client.fetch_url("https://example.com", agent_name="filter", run_id="run-denied")

        # 未授权调用不会访问 transport，而是直接返回 denied 日志和错误结果。
        self.assertFalse(result.log["success"])
        self.assertEqual(result.log["status"], "denied")
        self.assertEqual(result.log["run_id"], "run-denied")
        self.assertEqual(result.log["agent_name"], "filter")
        self.assertIn("cannot call tool", result.log["error_message"])
        self.assertEqual(result.result["error"]["code"], "MCP_PERMISSION_DENIED")


# 直接运行该测试文件时执行 unittest。
if __name__ == "__main__":
    unittest.main()
