from __future__ import annotations

from concurrent import futures
import logging
from typing import Any

import grpc

import agent_pb2
import agent_pb2_grpc
from app.config import Settings
from app.contracts import JsonDict
from app.workflow import ArticleWorkflow


LOGGER = logging.getLogger(__name__)


class AgentService(agent_pb2_grpc.AgentServiceServicer):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.workflow = ArticleWorkflow(settings)

    def HealthCheck(self, request: agent_pb2.HealthCheckRequest, context: grpc.ServicerContext):
        return agent_pb2.HealthCheckResponse(
            status="SERVING",
            version=self.settings.version,
            enabled_agents=self.workflow.enabled_agents(),
            mock_mode=self.workflow.llm_tool.provider_name == "mock" or self.settings.mock_mcp,
        )

    def ProcessArticles(self, request: agent_pb2.ProcessArticlesRequest, context: grpc.ServicerContext):
        result = self.workflow.process_articles(
            {
                "run_id": request.run_id,
                "articles": [
                    {
                        "article_id": item.article_id,
                        "url": item.url,
                        "title": item.title,
                        "raw_text": item.raw_text,
                        "source": item.source,
                        "published_at": item.published_at,
                        "tags": list(item.tags),
                    }
                    for item in request.articles
                ],
                "user_profile_snapshot": dict(request.user_profile_snapshot),
                "mcp_policy": _policy_to_dict(request.mcp_policy),
            }
        )
        response = agent_pb2.ProcessArticlesResponse(run_id=result["run_id"])
        for item in result.get("results", []):
            response.results.append(
                agent_pb2.ArticleProcessResult(
                    article_id=item["article_id"],
                    keep=item["keep"],
                    score=item["score"],
                    summary=item["summary"],
                    post_text=item["post_text"],
                    check_pass=item["check_pass"],
                    issues=item["issues"],
                    mcp_call_logs=[_log_to_proto(log) for log in item.get("mcp_call_logs", [])],
                )
            )
        return response

    def ProcessFeedback(self, request: agent_pb2.ProcessFeedbackRequest, context: grpc.ServicerContext):
        result = self.workflow.process_feedback(
            {
                "run_id": request.run_id,
                "feedback": [
                    {
                        "feedback_id": item.feedback_id,
                        "user_id": item.user_id,
                        "article_id": item.article_id,
                        "post_id": item.post_id,
                        "feedback_text": item.feedback_text,
                        "feedback_type": item.feedback_type,
                        "rating": item.rating,
                        "metadata": dict(item.metadata),
                    }
                    for item in request.feedback
                ],
                "user_profile_snapshot": dict(request.user_profile_snapshot),
                "mcp_policy": _policy_to_dict(request.mcp_policy),
            }
        )
        return agent_pb2.ProcessFeedbackResponse(
            run_id=result["run_id"],
            sentiment=result["sentiment"],
            extracted_feedback=list(result.get("extracted_feedback", [])),
            updated_profile_snapshot={str(k): str(v) for k, v in result.get("updated_profile_snapshot", {}).items()},
            mcp_call_logs=[_log_to_proto(log) for log in result.get("mcp_call_logs", [])],
        )


def create_server(settings: Settings) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    agent_pb2_grpc.add_AgentServiceServicer_to_server(AgentService(settings), server)
    return server


def serve(settings: Settings) -> None:
    server = create_server(settings)
    address = f"{settings.host}:{settings.port}"
    server.add_insecure_port(address)
    server.start()
    LOGGER.info("Python Agent protobuf gRPC server listening on %s", address)
    server.wait_for_termination()


def _policy_to_dict(policy: agent_pb2.McpPolicy) -> JsonDict:
    return {
        "mock_transport": policy.mock_transport,
        "enable_embedding": policy.enable_embedding,
        "enable_fetch": policy.enable_fetch,
        "enable_milvus": policy.enable_milvus,
        "enable_neo4j": policy.enable_neo4j,
    }


def _log_to_proto(log: dict[str, Any]) -> agent_pb2.McpCallLog:
    return agent_pb2.McpCallLog(
        run_id=str(log.get("run_id", "")),
        agent_name=str(log.get("agent_name", "")),
        server_name=str(log.get("server_name", "")),
        tool_name=str(log.get("tool_name", "")),
        request_json=str(log.get("request_json", "")),
        response_json=str(log.get("response_json", "")),
        success=bool(log.get("success", False)),
        status=str(log.get("status", "success" if log.get("success", False) else "failed")),
        error_message=str(log.get("error_message", "")),
        latency_ms=int(log.get("latency_ms", 0)),
    )
