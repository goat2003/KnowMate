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

from collections import OrderedDict
from concurrent import futures
import hashlib
import hmac
import json
import logging
import signal
from threading import Event, Lock
import time
from typing import Any

import grpc

import agent_pb2
import agent_pb2_grpc
from app.config import Settings
from app.contracts import JsonDict
from app.observability import METRICS, clear_run_id, set_run_id, tracer
from app.workflow import ArticleWorkflow


# LOGGER 用于记录 gRPC Server 启动地址等服务端日志。
LOGGER = logging.getLogger(__name__)


def _metadata_authorized(metadata, expected_token: str) -> bool:
    token = str(expected_token or "").strip()
    if not token:
        return True
    for key, value in metadata or ():
        lowered = str(key).lower()
        raw = str(value).strip()
        candidate = ""
        if lowered == "authorization" and raw.lower().startswith("bearer "):
            candidate = raw[7:].strip()
        elif lowered == "x-api-key":
            candidate = raw
        if candidate and hmac.compare_digest(candidate, token):
            return True
    return False


class AuthInterceptor(grpc.ServerInterceptor):
    def __init__(self, settings: Settings) -> None:
        self._token = settings.api_token

    def intercept_service(self, continuation, handler_call_details):
        if not self._token:
            return continuation(handler_call_details)
        if _metadata_authorized(handler_call_details.invocation_metadata, self._token):
            return continuation(handler_call_details)

        def abort(request, context):
            context.abort(grpc.StatusCode.UNAUTHENTICATED, "missing or invalid gRPC API token")

        return grpc.unary_unary_rpc_method_handler(abort)


class ResponseCache:
    def __init__(self, max_size: int) -> None:
        self.max_size = max(max_size, 1)
        self._responses: OrderedDict[str, bytes] = OrderedDict()
        self._inflight: dict[str, Event] = {}
        self._lock = Lock()

    def get_or_compute(self, key: str, response_type, compute):
        while True:
            with self._lock:
                cached = self._responses.get(key)
                if cached is not None:
                    self._responses.move_to_end(key)
                    response = response_type()
                    response.ParseFromString(cached)
                    return response
                event = self._inflight.get(key)
                if event is None:
                    event = Event()
                    self._inflight[key] = event
                    break
            event.wait()

        try:
            response = compute()
            encoded = response.SerializeToString(deterministic=True)
            with self._lock:
                self._responses[key] = encoded
                self._responses.move_to_end(key)
                while len(self._responses) > self.max_size:
                    self._responses.popitem(last=False)
            return response
        finally:
            with self._lock:
                event = self._inflight.pop(key)
                event.set()


def _request_key(method: str, request: Any) -> str:
    digest = hashlib.sha256(request.SerializeToString(deterministic=True)).hexdigest()
    return f"{method}:{digest}"


def _invalid_argument(context: grpc.ServicerContext | None, message: str) -> None:
    if context is None:
        raise ValueError(message)
    context.abort(grpc.StatusCode.INVALID_ARGUMENT, message)


def _score_breakdown_to_proto(item: dict[str, Any]) -> agent_pb2.ScoreBreakdownItem:
    return agent_pb2.ScoreBreakdownItem(
        dimension=str(item.get("dimension", "")),
        available=bool(item.get("available", False)),
        raw_score=float(item.get("raw_score", 0)),
        normalized_score=float(item.get("normalized_score", 0)),
        weight=float(item.get("weight", 0)),
        contribution=float(item.get("contribution", 0)),
        evidence=[str(value) for value in item.get("evidence", [])],
    )


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
        self.response_cache = ResponseCache(settings.idempotency_cache_size)

    def close(self) -> None:
        self.workflow.close()

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
        if not request.run_id:
            _invalid_argument(context, "run_id is required")
        if not request.articles:
            _invalid_argument(context, "at least one article is required")
        if len(request.articles) > self.settings.max_articles_per_request:
            _invalid_argument(
                context,
                f"article count exceeds max_articles_per_request={self.settings.max_articles_per_request}",
            )
        started = time.perf_counter()
        status = "OK"
        set_run_id(request.run_id)
        with tracer(__name__).start_as_current_span("AgentService.ProcessArticles") as span:
            span.set_attribute("run_id", request.run_id)
            span.set_attribute("article_count", len(request.articles))
            try:
                return self.response_cache.get_or_compute(
                    _request_key("ProcessArticles", request),
                    agent_pb2.ProcessArticlesResponse,
                    lambda: self._process_articles(request),
                )
            except Exception as exc:
                status = "error"
                span.record_exception(exc)
                raise
            finally:
                duration = time.perf_counter() - started
                METRICS.record_agent_run("grpc.ProcessArticles", "success" if status == "OK" else "failed", duration)
                METRICS.record_grpc_server("ProcessArticles", status, duration)
                clear_run_id()

    def _process_articles(self, request: agent_pb2.ProcessArticlesRequest):
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
                    score_breakdown=[_score_breakdown_to_proto(part) for part in item.get("score_breakdown", [])],
                    recommendation_reasons=[str(value) for value in item.get("recommendation_reasons", [])],
                    rejection_reasons=[str(value) for value in item.get("rejection_reasons", [])],
                    rank_position=int(item.get("rank_position", 0)),
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
        if not request.run_id:
            _invalid_argument(context, "run_id is required")
        if not request.feedback:
            _invalid_argument(context, "at least one feedback item is required")
        if len(request.feedback) > self.settings.max_feedback_per_request:
            _invalid_argument(
                context,
                f"feedback count exceeds max_feedback_per_request={self.settings.max_feedback_per_request}",
            )
        started = time.perf_counter()
        status = "OK"
        set_run_id(request.run_id)
        with tracer(__name__).start_as_current_span("AgentService.ProcessFeedback") as span:
            span.set_attribute("run_id", request.run_id)
            span.set_attribute("feedback_count", len(request.feedback))
            try:
                return self.response_cache.get_or_compute(
                    _request_key("ProcessFeedback", request),
                    agent_pb2.ProcessFeedbackResponse,
                    lambda: self._process_feedback(request),
                )
            except Exception as exc:
                status = "error"
                span.record_exception(exc)
                raise
            finally:
                duration = time.perf_counter() - started
                METRICS.record_agent_run("grpc.ProcessFeedback", "success" if status == "OK" else "failed", duration)
                METRICS.record_grpc_server("ProcessFeedback", status, duration)
                clear_run_id()

    def _process_feedback(self, request: agent_pb2.ProcessFeedbackRequest):
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
            structured_feedback_json=json.dumps(
                result.get("structured_feedback", {}),
                ensure_ascii=False,
                sort_keys=True,
            ),
            profile_diff_json=json.dumps(
                result.get("profile_diff", {}),
                ensure_ascii=False,
                sort_keys=True,
            ),
        )


# 函数作用：
# 创建 gRPC Server 并注册 AgentService。
#
# 参数说明：
# - settings：服务配置。
#
# 返回值：
# - 返回尚未 start 的 grpc.Server 对象。
def create_server(settings: Settings, service: AgentService | None = None) -> grpc.Server:
    # ThreadPoolExecutor(max_workers=10) 表示 gRPC 可以用最多 10 个工作线程处理并发请求。
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=settings.grpc_max_workers),
        interceptors=[AuthInterceptor(settings)],
        options=[
            ("grpc.max_receive_message_length", settings.grpc_max_message_bytes),
            ("grpc.max_send_message_length", settings.grpc_max_message_bytes),
        ],
    )
    # 将 AgentService 实例注册到 gRPC Server，注册函数由 protobuf 代码生成。
    agent_pb2_grpc.add_AgentServiceServicer_to_server(service or AgentService(settings), server)
    return server


def stop_grpc_server(server: grpc.Server, service: AgentService, grace_seconds: float = 5) -> None:
    stop_event = server.stop(grace=grace_seconds)
    wait = getattr(stop_event, "wait", None)
    if callable(wait):
        wait(timeout=max(float(grace_seconds), 0) + 1)
    service.close()


# 函数作用：
# 启动 Python Agent gRPC Server 并阻塞等待退出。
#
# 参数说明：
# - settings：服务配置，包含 host 和 port。
#
# 返回值：
# - 无返回；正常情况下会一直阻塞在 wait_for_termination。
def serve(settings: Settings) -> None:
    service = AgentService(settings)
    # 创建并注册服务。
    server = create_server(settings, service)
    # gRPC 监听地址，例如 0.0.0.0:50051。
    address = f"{settings.host}:{settings.port}"
    # add_insecure_port 表示不启用 TLS，适合本地或内网 MVP。
    server.add_insecure_port(address)
    # 启动服务开始接受请求。
    server.start()
    LOGGER.info("Python Agent protobuf gRPC server listening on %s", address)
    stop_requested = Event()

    def request_stop(signum, _frame) -> None:
        LOGGER.info("Python Agent received signal %s; stopping gRPC server", signum)
        stop_requested.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, request_stop)

    try:
        # 阻塞当前进程，直到收到终止信号。
        while not stop_requested.is_set():
            timed_out = server.wait_for_termination(timeout=1)
            if not timed_out:
                break
    finally:
        stop_grpc_server(server, service, grace_seconds=5)


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
        call_id=str(log.get("call_id", "")),
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
