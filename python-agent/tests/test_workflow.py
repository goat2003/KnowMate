import unittest

import agent_pb2

from app.config import Settings
from app.grpc_server import AgentService
from app.workflow import ArticleWorkflow


class ArticleWorkflowTest(unittest.TestCase):
    def test_article_workflow_produces_structured_result(self) -> None:
        workflow = ArticleWorkflow(Settings(mock_mcp=True))
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

    def test_mcp_failure_degrades_to_structured_result(self) -> None:
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


class AgentServiceTest(unittest.TestCase):
    def test_protobuf_service_process_articles(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
