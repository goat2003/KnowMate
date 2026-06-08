from __future__ import annotations

import unittest

import agent_pb2
from app.config import Settings
from app.grpc_server import AgentService
from app.observability import clear_run_id, current_run_id


class GrpcObservabilityTest(unittest.TestCase):
    def tearDown(self) -> None:
        clear_run_id()

    def test_process_articles_sets_and_clears_run_context(self) -> None:
        service = AgentService(Settings(mock_mcp=True))
        seen_run_ids: list[str | None] = []
        original = service.workflow.process_articles

        def wrapped(request):
            seen_run_ids.append(current_run_id())
            return original(request)

        service.workflow.process_articles = wrapped

        service.ProcessArticles(
            agent_pb2.ProcessArticlesRequest(
                run_id="grpc-observe",
                mcp_policy=agent_pb2.McpPolicy(mock_transport=True),
                articles=[
                    agent_pb2.Article(
                        article_id="a1",
                        url="https://example.com/a1",
                        title="A1",
                        raw_text="Agent observability content",
                    )
                ],
            ),
            None,
        )

        self.assertEqual(seen_run_ids, ["grpc-observe"])
        self.assertIn(current_run_id(), ("", None))

    def test_process_feedback_sets_and_clears_run_context(self) -> None:
        service = AgentService(Settings(mock_mcp=True))
        seen_run_ids: list[str | None] = []
        original = service.workflow.process_feedback

        def wrapped(request):
            seen_run_ids.append(current_run_id())
            return original(request)

        service.workflow.process_feedback = wrapped

        service.ProcessFeedback(
            agent_pb2.ProcessFeedbackRequest(
                run_id="grpc-feedback-observe",
                mcp_policy=agent_pb2.McpPolicy(mock_transport=True),
                feedback=[
                    agent_pb2.FeedbackItem(
                        feedback_id="f1",
                        user_id="u1",
                        article_id="a1",
                        feedback_text="useful",
                        feedback_type="like",
                        rating=5,
                    )
                ],
            ),
            None,
        )

        self.assertEqual(seen_run_ids, ["grpc-feedback-observe"])
        self.assertIn(current_run_id(), ("", None))
