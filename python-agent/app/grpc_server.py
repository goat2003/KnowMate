# 文件作用：
# 本文件实现 Python Agent Service 的 protobuf gRPC Server。
# 它接收 GoFrame 后端发来的 HealthCheck、ProcessArticles、ProcessFeedback 请求，
# 将 protobuf 对象转换为 Python 字典，调用 ArticleWorkflow，再把结果转换回 protobuf 响应。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的服务入口层，是 GoFrame 后端与 Python Agent 工作流之间的 gRPC 边界。
#
# 主要内容：
# 1. AgentService：实现 agent.proto 中定义的 AgentServiceServicer。
# 2. HealthCheck：返回服务状态、版本、启用 Agent 和 mock 模式。
# 3. ProcessArticles：处理文章列表请求。
# 4. ProcessFeedback：处理用户反馈请求。
# 5. create_server / serve：创建并启动 gRPC Server。
# 6. _policy_to_dict / _log_to_proto：在 protobuf 对象和 Python 字典之间做转换。
#
# 关键调用关系：
# - 被 server.py 调用启动。
# - 被 GoFrame 后端的 gRPC Client 调用。
# - 内部调用 app.workflow.ArticleWorkflow。
#
# 初学者阅读建议：
# 先对照 shared/proto/agent.proto 看请求和响应字段，
# 再看 ProcessArticles 如何把 request.articles 转成 ArticleWorkflow 需要的 dict。
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


# LOGGER 用于记录 gRPC Server 启动地址等服务端日志。
LOGGER = logging.getLogger(__name__)


# 类作用：
# AgentService 是 gRPC 服务实现类。
# 它继承 protobuf 生成的 AgentServiceServicer，并实现 proto 中声明的 RPC 方法。
class AgentService(agent_pb2_grpc.AgentServiceServicer):
    # 函数作用：
    # 初始化 gRPC 服务实例和内部工作流。
    #
    # 参数说明：
    # - settings：服务配置，包含监听地址、版本、LLM/MCP 配置等。
    #
    # 返回值：
    # - 构造函数不返回值。
    def __init__(self, settings: Settings) -> None:
        # 保存配置，HealthCheck 和 serve 会读取这些字段。
        self.settings = settings
        # ArticleWorkflow 是实际执行业务逻辑的对象。
        # gRPC 层只负责协议转换，不直接处理 Agent 细节。
        self.workflow = ArticleWorkflow(settings)

    # 函数作用：
    # gRPC 健康检查接口，用于 GoFrame 或运维侧确认 Python Agent Service 是否可用。
    #
    # 参数说明：
    # - request：HealthCheckRequest，目前没有业务字段。
    # - context：gRPC 上下文，可用于读取调用状态或设置错误；当前接口不需要使用。
    #
    # 返回值：
    # - 返回 HealthCheckResponse，包含 status、version、enabled_agents、mock_mode。
    def HealthCheck(self, request: agent_pb2.HealthCheckRequest, context: grpc.ServicerContext):
        # 直接构造 protobuf 响应对象。
        return agent_pb2.HealthCheckResponse(
            # SERVING 表示服务进程已启动并能处理请求。
            status="SERVING",
            # version 来自配置，便于 GoFrame 展示当前 Agent 版本。
            version=self.settings.version,
            # enabled_agents 告诉调用方当前工作流包含哪些 Agent。
            enabled_agents=self.workflow.enabled_agents(),
            # mock_mode 只要 LLM 是 mock 或 MCP 是 mock，就认为当前没有完全连接真实外部服务。
            mock_mode=self.workflow.llm_tool.provider_name == "mock" or self.settings.mock_mcp,
        )

    # 函数作用：
    # 处理 GoFrame 发来的文章处理 gRPC 请求。
    #
    # 参数说明：
    # - request：ProcessArticlesRequest，包含 run_id、articles、user_profile_snapshot、mcp_policy。
    # - context：gRPC 上下文对象，当前未设置额外状态。
    #
    # 返回值：
    # - 返回 ProcessArticlesResponse，包含每篇文章的处理结果和 MCP 调用日志。
    #
    # 调用关系：
    # - 被 GoFrame gRPC Client 调用。
    # - 内部调用 ArticleWorkflow.process_articles。
    def ProcessArticles(self, request: agent_pb2.ProcessArticlesRequest, context: grpc.ServicerContext):
        # 将 protobuf 请求转换成普通 Python dict，降低工作流层对 protobuf 生成类型的依赖。
        result = self.workflow.process_articles(
            {
                # run_id 用于串联本次任务的数据库日志和 MCP 调用日志。
                "run_id": request.run_id,
                # 将 repeated ArticleInput 转为 list[dict]，每项字段保持与 normalize_article 兼容。
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
                # protobuf map 转成普通 dict，供 Agent 读取用户画像。
                "user_profile_snapshot": dict(request.user_profile_snapshot),
                # McpPolicy protobuf 转成普通 dict，供 ArticleWorkflow 合并默认策略。
                "mcp_policy": _policy_to_dict(request.mcp_policy),
            }
        )
        # 创建响应对象，run_id 使用工作流返回值，可能是请求值或自动生成值。
        response = agent_pb2.ProcessArticlesResponse(run_id=result["run_id"])
        # 逐篇把 Python dict 结果追加到 protobuf repeated results 中。
        for item in result.get("results", []):
            response.results.append(
                agent_pb2.ArticleProcessResult(
                    # 字段名和 agent.proto 中 ArticleProcessResult 对应。
                    article_id=item["article_id"],
                    keep=item["keep"],
                    score=item["score"],
                    summary=item["summary"],
                    post_text=item["post_text"],
                    check_pass=item["check_pass"],
                    issues=item["issues"],
                    # 每条 MCP 日志也需要转换为 protobuf message。
                    mcp_call_logs=[_log_to_proto(log) for log in item.get("mcp_call_logs", [])],
                )
            )
        return response

    # 函数作用：
    # 处理 GoFrame 发来的用户反馈 gRPC 请求。
    #
    # 参数说明：
    # - request：ProcessFeedbackRequest，包含反馈列表、用户画像快照和 MCP 策略。
    # - context：gRPC 上下文对象，当前未设置额外状态。
    #
    # 返回值：
    # - 返回 ProcessFeedbackResponse，包含情绪、偏好信号、更新后的画像和 MCP 日志。
    #
    # 调用关系：
    # - 被 GoFrame gRPC Client 调用。
    # - 内部调用 ArticleWorkflow.process_feedback。
    def ProcessFeedback(self, request: agent_pb2.ProcessFeedbackRequest, context: grpc.ServicerContext):
        # 将 protobuf FeedbackInput 列表转换为 Python dict 列表。
        result = self.workflow.process_feedback(
            {
                # run_id 关联本次反馈处理任务。
                "run_id": request.run_id,
                # list comprehension 把每条反馈展开为工作流可处理的字段。
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
                # 当前用户画像快照会被 MemoryAgent 复制并更新。
                "user_profile_snapshot": dict(request.user_profile_snapshot),
                # MCP 策略决定反馈流程能否调用 embedding/neo4j。
                "mcp_policy": _policy_to_dict(request.mcp_policy),
            }
        )
        # 构造反馈响应；map 字段要求 key/value 都是字符串。
        return agent_pb2.ProcessFeedbackResponse(
            run_id=result["run_id"],
            sentiment=result["sentiment"],
            extracted_feedback=list(result.get("extracted_feedback", [])),
            # updated_profile_snapshot 统一转成 str，匹配 proto 的 map<string,string>。
            updated_profile_snapshot={str(k): str(v) for k, v in result.get("updated_profile_snapshot", {}).items()},
            # 顶层 MCP 调用日志来自 MemoryAgent。
            mcp_call_logs=[_log_to_proto(log) for log in result.get("mcp_call_logs", [])],
        )


# 函数作用：
# 创建 gRPC Server 并注册 AgentService。
#
# 参数说明：
# - settings：服务配置。
#
# 返回值：
# - 返回尚未 start 的 grpc.Server 对象。
def create_server(settings: Settings) -> grpc.Server:
    # ThreadPoolExecutor(max_workers=10) 表示 gRPC 可以用最多 10 个工作线程处理并发请求。
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    # 将 AgentService 实例注册到 gRPC Server，注册函数由 protobuf 代码生成。
    agent_pb2_grpc.add_AgentServiceServicer_to_server(AgentService(settings), server)
    return server


# 函数作用：
# 启动 Python Agent gRPC Server 并阻塞等待退出。
#
# 参数说明：
# - settings：服务配置，包含 host 和 port。
#
# 返回值：
# - 无返回；正常情况下会一直阻塞在 wait_for_termination。
def serve(settings: Settings) -> None:
    # 创建并注册服务。
    server = create_server(settings)
    # gRPC 监听地址，例如 0.0.0.0:50051。
    address = f"{settings.host}:{settings.port}"
    # add_insecure_port 表示不启用 TLS，适合本地或内网 MVP。
    server.add_insecure_port(address)
    # 启动服务开始接受请求。
    server.start()
    LOGGER.info("Python Agent protobuf gRPC server listening on %s", address)
    # 阻塞当前进程，直到收到终止信号。
    server.wait_for_termination()


# 函数作用：
# 将 protobuf McpPolicy 转换为普通 Python dict。
#
# 参数说明：
# - policy：agent.proto 中定义的 McpPolicy 消息。
#
# 返回值：
# - 返回 dict，供 ArticleWorkflow.default_mcp_policy 合并默认值。
def _policy_to_dict(policy: agent_pb2.McpPolicy) -> JsonDict:
    # 每个 bool 字段都原样取出，字段名和工作流层的策略 key 保持一致。
    return {
        "mock_transport": policy.mock_transport,
        "enable_embedding": policy.enable_embedding,
        "enable_fetch": policy.enable_fetch,
        "enable_milvus": policy.enable_milvus,
        "enable_neo4j": policy.enable_neo4j,
    }


# 函数作用：
# 将 Python dict 形式的 MCP 调用日志转换成 protobuf McpCallLog。
#
# 参数说明：
# - log：BaseMcpClient._result 生成的日志字典。
#
# 返回值：
# - 返回 agent_pb2.McpCallLog 对象。
def _log_to_proto(log: dict[str, Any]) -> agent_pb2.McpCallLog:
    # 每个字段都做显式类型转换，避免 None 或非预期类型导致 protobuf 构造失败。
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
