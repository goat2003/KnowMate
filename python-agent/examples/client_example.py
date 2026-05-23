from __future__ import annotations

import grpc

import agent_pb2
import agent_pb2_grpc


def main() -> None:
    with grpc.insecure_channel("127.0.0.1:50051") as channel:
        stub = agent_pb2_grpc.AgentServiceStub(channel)

        health = stub.HealthCheck(agent_pb2.HealthCheckRequest(client="python-example"))
        print("HealthCheck:", health)

        articles = stub.ProcessArticles(
            agent_pb2.ProcessArticlesRequest(
                run_id="example-run",
                user_profile_snapshot={"interests": "AI,知识管理,工程实践"},
                mcp_policy=agent_pb2.McpPolicy(
                    mock_transport=True,
                    enable_embedding=True,
                    enable_milvus=True,
                    enable_neo4j=True,
                ),
                articles=[
                    agent_pb2.Article(
                        article_id="article-001",
                        url="https://example.com/article-001",
                        title="Agent Workflow for Knowledge Posts",
                        raw_text="This article explains how to compose filter, summary, rewrite, and check nodes.",
                        tags=["agent", "workflow"],
                    )
                ],
            )
        )
        print("ProcessArticles:", articles)

        feedback = stub.ProcessFeedback(
            agent_pb2.ProcessFeedbackRequest(
                run_id="feedback-run",
                user_profile_snapshot={"feedback_count": "0"},
                mcp_policy=agent_pb2.McpPolicy(mock_transport=True, enable_embedding=True, enable_neo4j=True),
                feedback=[
                    agent_pb2.FeedbackItem(
                        feedback_id="feedback-001",
                        user_id="user-001",
                        article_id="article-001",
                        feedback_text="摘要有用，但希望保留更多工程实践细节",
                        rating=5,
                    )
                ],
            )
        )
        print("ProcessFeedback:", feedback)


if __name__ == "__main__":
    main()
