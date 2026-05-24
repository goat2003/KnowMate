# 文件作用：
# 本文件定义 Python Agent Service 调用 MCP Server 的统一底座。
# 它包含 MCP 传输层协议、mock 传输、真实 JSON-RPC 传输、统一调用入口和 MCP 调用日志生成。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 MCP Client 层，被 embedding/fetch/milvus/neo4j 具体 Client 继承或使用。
#
# 主要内容：
# 1. McpTransport：定义传输层必须实现的 call 接口。
# 2. McpCallResult：封装工具调用结果和标准日志。
# 3. MockMcpTransport：本地模拟 MCP Server，适合离线测试。
# 4. JsonRpcMcpTransport：通过 HTTP JSON-RPC 调用真实 MCP Server。
# 5. BaseMcpClient：统一执行权限校验、工具调用、异常降级和日志生成。
#
# 关键调用关系：
# - 被 EmbeddingClient、FetchClient、MilvusClient、Neo4jClient 继承。
# - 被 FilterAgent 和 MemoryAgent 间接调用。
# - 生成的 log 会进入 ProcessArticlesResponse / ProcessFeedbackResponse，再由 GoFrame 写入 mcp_call_logs 表。
#
# 初学者阅读建议：
# 先看 BaseMcpClient.call_tool 的调用流程，再看 MockMcpTransport 和 JsonRpcMcpTransport 的区别。
from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any, Protocol
from urllib import request as urlrequest
from uuid import uuid4

from app.contracts import JsonDict
from app.mcp.policy import MCPPolicy


# 类作用：
# McpTransport 是 Python 的 Protocol，用来描述 MCP 传输层需要具备的 call 方法。
# Protocol 类似 Go 的 interface：只要对象拥有同名方法，就可以被当作这个协议使用。
class McpTransport(Protocol):
    # 函数作用：
    # 调用指定 MCP Server 的指定 Tool。
    #
    # 参数说明：
    # - server_name：MCP Server 名称，例如 embedding-mcp、fetch-mcp。
    # - tool_name：MCP Tool 名称，例如 embed_text、fetch_webpage。
    # - payload：工具参数字典。
    #
    # 返回值：
    # - 返回工具输出字典。
    def call(self, server_name: str, tool_name: str, payload: JsonDict) -> JsonDict:
        # Protocol 中的省略号表示这里只声明接口，不实现逻辑。
        ...


# 类作用：
# McpCallResult 用 dataclass 封装一次 MCP 调用的业务结果和日志。
# slots=True 减少实例动态属性，适合这种字段固定的小对象。
@dataclass(slots=True)
class McpCallResult:
    # result 是 MCP Tool 的业务输出，Agent 会读取它继续处理。
    result: JsonDict
    # log 是标准化调用日志，最终会写入 mcp_call_logs 表。
    log: JsonDict


# 类作用：
# MockMcpTransport 是本地模拟 MCP 传输层。
# 它不访问真实网络，而是按 server_name/tool_name 返回固定结构，方便单元测试和离线运行。
class MockMcpTransport:
    # 函数作用：
    # 模拟一次 MCP 工具调用。
    #
    # 参数说明：
    # - server_name：模拟的 MCP Server 名称。
    # - tool_name：模拟的工具名称。
    # - payload：工具入参。
    #
    # 返回值：
    # - 返回与真实 MCP Tool 形状相近的字典。
    def call(self, server_name: str, tool_name: str, payload: JsonDict) -> JsonDict:
        # embedding-mcp 模拟文本向量化。
        if server_name == "embedding-mcp":
            # embed_batch 批量处理多段文本。
            if tool_name == "embed_batch":
                embeddings = [self._embedding(str(text)) for text in payload.get("texts", [])]
                return {"embeddings": embeddings, "dim": 3}
            # 其他 embedding 工具默认按单文本处理。
            text = str(payload.get("text", ""))
            return {"embedding": self._embedding(text), "dim": 3}
        # milvus-mcp 模拟向量库检索和去重。
        if server_name == "milvus-mcp":
            # semantic_deduplicate 模拟语义去重，mock 中直接认为所有 items 都是唯一的。
            if tool_name == "semantic_deduplicate":
                return {"unique_items": payload.get("items", []), "duplicates": []}
            # 其他检索类工具返回一个固定相似记忆。
            return {"matches": [{"article_id": "mock-related-1", "score": 0.81}]}
        # neo4j-mcp 模拟用户兴趣图谱读写。
        if server_name == "neo4j-mcp":
            # 更新类工具返回 updated=True，表示图谱写入成功。
            if tool_name in {"update_profile", "update_user_interest_graph"}:
                return {"updated": True, "profile_patch": payload}
            # 查询类工具返回固定主题列表，用于本地筛选加分。
            return {"topics": ["AI", "knowledge-management", "engineering"], "user_id": payload.get("user_id", "")}
        # fetch-mcp 模拟网页抓取和清洗。
        if server_name == "fetch-mcp":
            # check_url_alive 根据 URL 是否存在返回存活状态。
            if tool_name == "check_url_alive":
                return {"alive": bool(payload.get("url")), "status_code": 200 if payload.get("url") else 0}
            # extract_main_content 在 mock 中直接把 html 当正文返回。
            if tool_name == "extract_main_content":
                return {"raw_text": str(payload.get("html", ""))}
            # clean_html 只做非常简单的 script 标签移除，不能代表真实 HTML 清洗能力。
            if tool_name == "clean_html":
                return {"html": str(payload.get("html", "")).replace("<script>", "").replace("</script>", "")}
            # fetch_webpage 等默认抓取工具返回固定 mock 文档。
            return {"title": "Mock fetched document", "raw_text": "This text was fetched by mock transport."}
        # 未识别的 server 也返回 ok，避免 mock 模式因为未知工具打断主流程。
        return {"ok": True}

    # 函数作用：
    # 根据文本生成一个稳定的三维 mock 向量。
    #
    # 参数说明：
    # - text：待向量化文本。
    #
    # 返回值：
    # - 返回三维 float 列表，只用于测试，不代表真实 embedding。
    def _embedding(self, text: str) -> list[float]:
        # 用文本长度取模生成第一维，让不同文本至少产生一点差异。
        return [round((len(text) % 13) / 13, 4), 0.37, 0.61]


# 类作用：
# JsonRpcMcpTransport 是真实 MCP Server 的 HTTP JSON-RPC 传输层。
# 它把 BaseMcpClient 的调用转换为 POST /rpc 请求。
class JsonRpcMcpTransport:
    # 函数作用：
    # 保存 MCP Server endpoint 配置。
    #
    # 参数说明：
    # - endpoints：server 名称到 URL 的映射，例如 {"embedding": "http://127.0.0.1:7001"}。
    def __init__(self, endpoints: dict[str, str]) -> None:
        # endpoints 通常来自 python-agent/config.yaml 或环境变量。
        self.endpoints = endpoints

    # 函数作用：
    # 通过 JSON-RPC 调用真实 MCP Tool。
    #
    # 参数说明：
    # - server_name：MCP Server 名称。
    # - tool_name：MCP Tool 名称。
    # - payload：工具参数。
    #
    # 返回值：
    # - 返回 MCP Server result/output 字典。
    #
    # 异常说明：
    # - endpoint 缺失、网络失败、JSON-RPC error 或响应格式不对都会抛异常；
    #   BaseMcpClient.call_tool 会捕获这些异常并转换为失败日志。
    def call(self, server_name: str, tool_name: str, payload: JsonDict) -> JsonDict:
        # 根据 server_name 找到配置中的 endpoint，并去除末尾斜杠便于拼接 /rpc。
        base_url = self._endpoint(server_name).rstrip("/")
        # 构造标准 JSON-RPC 2.0 请求信封。
        request_payload = {
            "jsonrpc": "2.0",
            # uuid4().hex 生成请求 id，便于排查单次工具调用。
            "id": uuid4().hex,
            # MCP 的工具调用方法名。
            "method": "tools/call",
            # params 中 name 是工具名，arguments 是工具参数。
            "params": {"name": tool_name, "arguments": payload},
        }
        # 将请求信封编码为 UTF-8 JSON 字节。
        body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
        # 使用标准库构造 HTTP POST 请求，避免额外依赖 requests。
        req = urlrequest.Request(
            f"{base_url}/rpc",
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        # 发送请求并解析响应 JSON。
        with urlrequest.urlopen(req, timeout=8) as response:
            envelope = json.loads(response.read().decode("utf-8"))
        # JSON-RPC error 字段表示工具调用失败，应转成异常交给 BaseMcpClient 记录。
        if "error" in envelope:
            message = envelope["error"].get("message", "MCP JSON-RPC error")
            raise RuntimeError(f"{server_name}.{tool_name}: {message}")
        # result 是 JSON-RPC 成功响应的主体。
        result = envelope.get("result", {})
        # 某些 MCP Server 会把真实输出放在 result.output 中，这里兼容该结构。
        if isinstance(result, dict) and isinstance(result.get("output"), dict):
            return result["output"]
        # 如果 result 本身就是字典，就直接作为工具输出。
        if isinstance(result, dict):
            return result
        # 非字典结果不符合本项目 MCP Client 约定。
        raise RuntimeError(f"{server_name}.{tool_name}: invalid JSON-RPC result")

    # 函数作用：
    # 从 endpoints 中查找某个 MCP Server 的 URL。
    #
    # 参数说明：
    # - server_name：例如 embedding-mcp、milvus-mcp。
    #
    # 返回值：
    # - 返回 endpoint URL 字符串。
    def _endpoint(self, server_name: str) -> str:
        # candidates 支持多种 key 写法，兼容配置里写 embedding 或 embedding_mcp 等形式。
        candidates = [
            server_name,
            server_name.replace("-mcp", ""),
            server_name.replace("-", "_"),
            server_name.replace("-mcp", "").replace("-", "_"),
        ]
        # 按候选顺序查找第一个非空 URL。
        for key in candidates:
            if self.endpoints.get(key):
                return self.endpoints[key]
        # 找不到 endpoint 时抛错，BaseMcpClient 会记录为 MCP_CALL_FAILED。
        raise RuntimeError(f"No MCP endpoint configured for `{server_name}`")


# 类作用：
# BaseMcpClient 是所有具体 MCP Client 的父类。
# 它集中处理权限检查、工具调用、失败降级和日志结构，避免每个 Client 重复实现。
class BaseMcpClient:
    # 子类会覆盖 server_name，例如 EmbeddingClient 设置为 embedding-mcp。
    server_name = "mcp"

    # 函数作用：
    # 初始化 MCP Client。
    #
    # 参数说明：
    # - transport：MCP 传输层，可以是真实 JSON-RPC 或 mock。
    # - policy：MCP 权限策略，控制 Agent 能否调用某个工具。
    def __init__(self, transport: McpTransport, policy: MCPPolicy | None = None) -> None:
        # transport 只负责真正发起或模拟工具调用。
        self.transport = transport
        # policy 为空时使用默认权限表。
        self.policy = policy or MCPPolicy()

    # 函数作用：
    # 统一调用 MCP Tool，并生成 mcp_call_logs 所需日志。
    #
    # 参数说明：
    # - tool_name：工具名，例如 embed_text。
    # - payload：工具参数。
    # - agent_name：发起调用的 Agent 名称，用于权限控制和日志。
    # - run_id：任务 id，用于关联 run_logs。
    #
    # 返回值：
    # - 返回 McpCallResult，包含 result 和 log。
    #
    # 权限控制：
    # - 调用前先执行 MCPPolicy.check。
    # - 未授权不会访问 transport，而是返回 MCP_PERMISSION_DENIED 结果和 denied 日志。
    #
    # 失败降级：
    # - transport 抛异常时不会让 Agent 崩溃，而是返回 MCP_CALL_FAILED 结果和 failed 日志。
    def call_tool(self, tool_name: str, payload: JsonDict, *, agent_name: str, run_id: str) -> McpCallResult:
        # 记录开始时间，用于计算 latency_ms。
        started = time.perf_counter()
        # 记录标准 JSON-RPC 请求体到日志，方便后续排查工具入参。
        request_payload = {
            "jsonrpc": "2.0",
            "id": uuid4().hex,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": payload},
        }
        # 默认认为调用失败，只有 transport 成功返回后才改为 True。
        success = False
        status = "failed"
        error_message = ""
        result: JsonDict

        # 权限检查是 MCP 安全边界：Agent 只能调用权限表中允许的工具。
        decision = self.policy.check(agent_name, tool_name)
        # 未授权时立即构造错误结果，不会真正访问 MCP Server。
        if not decision.allowed:
            error_message = decision.error_message
            result = {"error": {"code": "MCP_PERMISSION_DENIED", "message": error_message}}
            response_payload: JsonDict = {
                "jsonrpc": "2.0",
                "error": {"code": "MCP_PERMISSION_DENIED", "message": error_message},
            }
            status = "denied"
            # 计算权限拒绝路径的耗时。
            latency_ms = int((time.perf_counter() - started) * 1000)
            # 返回统一结构，Agent 可以把 log 继续追加到结果中。
            return self._result(
                result=result,
                request_payload=request_payload,
                response_payload=response_payload,
                run_id=run_id,
                agent_name=agent_name,
                tool_name=tool_name,
                success=success,
                status=status,
                error_message=error_message,
                latency_ms=latency_ms,
            )

        # 已授权时才进入真实或 mock transport 调用。
        try:
            result = self.transport.call(self.server_name, tool_name, payload)
            response_payload: JsonDict = {"jsonrpc": "2.0", "result": result}
            success = True
            status = "success"
        except Exception as exc:  # pragma: no cover - real transport path
            # 真实 MCP Server 可能网络失败、超时或返回异常；这里统一转换为失败结果，不中断主流程。
            error_message = str(exc)
            result = {"error": {"code": "MCP_CALL_FAILED", "message": error_message}}
            response_payload = {
                "jsonrpc": "2.0",
                "error": {"code": "MCP_CALL_FAILED", "message": error_message},
            }
            status = "failed"
        # 计算总耗时，单位毫秒，便于 mcp_call_logs 分析慢工具。
        latency_ms = int((time.perf_counter() - started) * 1000)
        # 无论成功或失败，都返回同样结构，减少 Agent 的分支判断。
        return self._result(
            result=result,
            request_payload=request_payload,
            response_payload=response_payload,
            run_id=run_id,
            agent_name=agent_name,
            tool_name=tool_name,
            success=success,
            status=status,
            error_message=error_message,
            latency_ms=latency_ms,
        )

    # 函数作用：
    # 组装统一 McpCallResult。
    #
    # 参数说明：
    # - result：工具业务输出或错误对象。
    # - request_payload：记录到日志的 JSON-RPC 请求体。
    # - response_payload：记录到日志的 JSON-RPC 响应体。
    # - run_id：任务 id。
    # - agent_name：发起调用的 Agent。
    # - tool_name：工具名。
    # - success：是否成功。
    # - status：success / failed / denied 等状态。
    # - error_message：失败或拒绝原因。
    # - latency_ms：调用耗时。
    #
    # 返回值：
    # - 返回 McpCallResult。
    def _result(
        self,
        *,
        result: JsonDict,
        request_payload: JsonDict,
        response_payload: JsonDict,
        run_id: str,
        agent_name: str,
        tool_name: str,
        success: bool,
        status: str,
        error_message: str,
        latency_ms: int,
    ) -> McpCallResult:
        # McpCallResult 同时给 Agent 业务结果和 GoFrame 可持久化日志。
        return McpCallResult(
            result=result,
            log={
                # run_id 关联一次完整任务。
                "run_id": run_id,
                # agent_name 表示哪个 Agent 发起了调用。
                "agent_name": agent_name,
                # server_name 表示调用哪个 MCP Server。
                "server_name": self.server_name,
                # tool_name 表示调用哪个 MCP Tool。
                "tool_name": tool_name,
                # request_json 和 response_json 用字符串保存，便于数据库字段直接存储 JSON 文本。
                "request_json": json.dumps(request_payload, ensure_ascii=False),
                "response_json": json.dumps(response_payload, ensure_ascii=False),
                # status 和 success 同时存在，方便人读和程序过滤。
                "status": status,
                "error_message": error_message,
                "success": success,
                # latency_ms 用于观察 MCP Server 性能和超时问题。
                "latency_ms": latency_ms,
            },
        )
