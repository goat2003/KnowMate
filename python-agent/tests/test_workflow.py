# 文件作用：
# 本文件测试 Python Agent 的核心工作流和 gRPC 服务封装。
# 它验证文章处理、反馈处理、MCP 失败降级、MCP 权限拒绝日志，以及 protobuf 服务响应。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的测试层。
#
# 主要内容：
# 1. ArticleWorkflowTest：直接测试 ArticleWorkflow。
# 2. AgentServiceTest：测试 gRPC service 方法能把 protobuf 请求转成响应。
#
# 关键调用关系：
# - 调用 app.workflow.ArticleWorkflow。
# - 调用 app.grpc_server.AgentService。
#
# 初学者阅读建议：
# 这些测试使用 mock LLM/MCP，目的是验证数据结构和流程，不代表真实外部服务效果。
import unittest

import agent_pb2

from app.config import Settings
from app.grpc_server import AgentService
from app.workflow import ArticleWorkflow


# 类作用：
# ArticleWorkflowTest 覆盖 Python Agent 内部工作流。
class ArticleWorkflowTest(unittest.TestCase):
    # 函数作用：
    # 验证文章工作流能产出结构化结果、MCP 日志和通过校验的 post_text。
    def test_article_workflow_produces_structured_result(self) -> None:
        # 使用 mock_mcp=True，避免测试依赖真实 MCP Server。
        workflow = ArticleWorkflow(Settings(mock_mcp=True))
        # 构造与 gRPC 请求形状相近的 Python dict。
        result = workflow.process_articles(
            {
                "run_id": "test-run",
                "user_profile_snapshot": {"interests": "AI,knowledge-management"},
                "mcp_policy": {
                    "mock_transport": True,
                    "enable_embedding": True,
                    "enable_milvus": True,
                    "enable_neo4j": True,
                },
                "articles": [
                    {
                        "article_id": "a1",
                        "url": "https://example.com/a1",
                        "title": "AI Knowledge Graph Notes",
                        "raw_text": "This article explains how agent systems can use knowledge graphs and workflow nodes.",
                        "tags": ["agent"],
                    }
                ],
            }
        )

        # 以下断言验证 run_id、筛选结果、摘要、推文、校验状态和 MCP 日志。
        self.assertEqual(result["run_id"], "test-run")
        item = result["results"][0]
        self.assertEqual(item["article_id"], "a1")
        self.assertTrue(item["keep"])
        self.assertGreaterEqual(item["score"], 0.5)
        self.assertTrue(item["summary"].startswith("这篇文章"))
        self.assertIn("【知识笔记】", item["post_text"])
        self.assertTrue(item["check_pass"])
        self.assertTrue(item["mcp_call_logs"])
        self.assertTrue(all(log["run_id"] == "test-run" for log in item["mcp_call_logs"]))
        self.assertTrue(all(log["agent_name"] == "filter" for log in item["mcp_call_logs"]))
        self.assertTrue(all(log["status"] == "success" for log in item["mcp_call_logs"]))

    # 函数作用：
    # 验证反馈工作流会更新用户画像快照，并产生 memory Agent 的 MCP 调用日志。
    def test_feedback_workflow_updates_profile(self) -> None:
        workflow = ArticleWorkflow(Settings(mock_mcp=True))
        result = workflow.process_feedback(
            {
                "run_id": "feedback-run",
                "user_profile_snapshot": {"feedback_count": "1"},
                "mcp_policy": {"mock_transport": True, "enable_embedding": True, "enable_neo4j": True},
                "feedback": [
                    {
                        "feedback_id": "f1",
                        "feedback_text": "这个摘要有用，希望多保留工程实践细节",
                        "rating": 5,
                    }
                ],
            }
        )

        self.assertEqual(result["sentiment"], "positive")
        self.assertEqual(result["updated_profile_snapshot"]["feedback_count"], "2")
        self.assertTrue(result["extracted_feedback"])
        self.assertTrue(result["mcp_call_logs"])
        self.assertTrue(all(log["run_id"] == "feedback-run" for log in result["mcp_call_logs"]))
        self.assertTrue(all(log["agent_name"] == "memory" for log in result["mcp_call_logs"]))

    # 函数作用：
    # 验证真实 MCP endpoint 不可用时，工作流不会崩溃，而是返回 failed MCP 日志。
    def test_mcp_failure_degrades_to_structured_result(self) -> None:
        # 127.0.0.1:1 通常没有服务监听，用来模拟 MCP 连接失败。
        workflow = ArticleWorkflow(
            Settings(
                mock_mcp=False,
                mcp_urls={
                    "embedding": "http://127.0.0.1:1",
                    "milvus": "http://127.0.0.1:1",
                    "neo4j": "http://127.0.0.1:1",
                    "fetch": "http://127.0.0.1:1",
                },
            )
        )
        result = workflow.process_articles(
            {
                "run_id": "mcp-failure",
                "user_profile_snapshot": {"interests": "AI"},
                "mcp_policy": {"enable_embedding": True, "enable_milvus": True, "enable_neo4j": True},
                "articles": [
                    {
                        "article_id": "a-fail",
                        "url": "https://example.com/a-fail",
                        "title": "AI workflow",
                        "raw_text": "Short but valid article text about AI workflow.",
                    }
                ],
            }
        )

        item = result["results"][0]
        self.assertTrue(item["keep"])
        self.assertTrue(item["check_pass"])
        self.assertTrue(any(log["status"] == "failed" for log in item["mcp_call_logs"]))

    # 函数作用：
    # 验证 FilterAgent 越权调用 fetch_webpage 时，MCPPolicy 会返回 denied 日志。
    def test_process_articles_returns_permission_denied_log(self) -> None:
        workflow = ArticleWorkflow(Settings(mock_mcp=True))
        result = workflow.process_articles(
            {
                "run_id": "permission-denied-run",
                "user_profile_snapshot": {"interests": "AI"},
                "mcp_policy": {"enable_fetch": True, "enable_embedding": True},
                "articles": [
                    {
                        "article_id": "a-denied",
                        "url": "https://example.com/denied",
                        "title": "AI workflow",
                        "raw_text": "",
                    }
                ],
            }
        )

        logs = result["results"][0]["mcp_call_logs"]
        self.assertTrue(any(log["tool_name"] == "fetch_webpage" and log["status"] == "denied" for log in logs))
        self.assertTrue(result["results"][0]["post_text"] or result["results"][0]["issues"])


# 类作用：
# AgentServiceTest 覆盖 gRPC service 层的 protobuf 转换。
class AgentServiceTest(unittest.TestCase):
    # 函数作用：
    # 验证 ProcessArticles 能接收 protobuf 请求并返回 protobuf 响应。
    def test_protobuf_service_process_articles(self) -> None:
        # 直接实例化服务类，不启动真实网络端口。
        service = AgentService(Settings(mock_mcp=True))
        response = service.ProcessArticles(
            agent_pb2.ProcessArticlesRequest(
                run_id="grpc-test",
                user_profile_snapshot={"interests": "AI"},
                mcp_policy=agent_pb2.McpPolicy(
                    mock_transport=True,
                    enable_embedding=True,
                    enable_milvus=True,
                    enable_neo4j=True,
                ),
                articles=[
                    agent_pb2.Article(
                        article_id="a2",
                        url="https://example.com/a2",
                        title="AI Agent Workflow",
                        raw_text="A practical article about agents, deterministic routing, and workflow checks.",
                    )
                ],
            ),
            None,
        )

        self.assertEqual(response.run_id, "grpc-test")
        self.assertEqual(response.results[0].article_id, "a2")
        self.assertTrue(response.results[0].check_pass)


# 直接运行该测试文件时执行 unittest。
if __name__ == "__main__":
    unittest.main()
