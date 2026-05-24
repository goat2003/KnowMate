# 文件作用：
# 本文件实现一个轻量 HTTP MCP Server 框架。
# 各个 MCP Server（embedding/fetch/milvus/neo4j）复用它来暴露 /health、/tools、/rpc 和 /call 接口。
#
# 在项目中的位置：
# 本文件属于 MCP Servers 的公共基础层，不直接提供业务工具，而是提供 JSON-RPC 和工具注册能力。
#
# 主要内容：
# 1. ToolError：工具调用错误类型，可转换为 JSON-RPC error。
# 2. ToolSpec：描述 MCP Tool 的名称、说明、输入输出 schema 和示例。
# 3. require_* / optional_*：工具入参校验辅助函数。
# 4. run_server：启动 HTTP Server 并处理 MCP JSON-RPC 请求。
#
# 关键调用关系：
# - 被 mcp-servers/*-mcp/server.py 导入。
# - 被 Python Agent 的 JsonRpcMcpTransport 通过 POST /rpc 调用。
#
# 初学者阅读建议：
# 先看 run_server 如何把 tools/call 转发给具体 server.py 的 handle 函数，
# 再看 BaseMcpClient 如何把 Agent 的工具调用转换成 JSON-RPC 请求。
from __future__ import annotations

from dataclasses import dataclass, asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from typing import Callable, Any
from uuid import uuid4


# JsonDict 统一表示 JSON 对象字典。
JsonDict = dict[str, Any]
# ToolHandler 是具体 MCP Server 必须提供的处理函数类型。
# 第一个参数是 tool_name，第二个参数是 arguments/payload。
ToolHandler = Callable[[str, JsonDict], JsonDict]


# 类作用：
# ToolError 表示 MCP Tool 参数错误、未知工具或业务错误。
# run_server 会捕获它并转换成 JSON-RPC error 响应。
class ToolError(Exception):
    # 函数作用：
    # 创建工具错误。
    #
    # 参数说明：
    # - message：错误说明。
    # - code：JSON-RPC error code，默认 -32000 表示服务端业务错误。
    # - data：附加错误数据。
    def __init__(self, message: str, code: int = -32000, data: JsonDict | None = None) -> None:
        # 调用 Exception 父类构造函数，让错误也能被普通异常机制处理。
        super().__init__(message)
        # message 会写入 JSON-RPC error.message。
        self.message = message
        # code 会写入 JSON-RPC error.code。
        self.code = code
        # data 用于附加字段名、工具名等排查信息。
        self.data = data or {}


# 类作用：
# ToolSpec 描述一个 MCP Tool 的元数据。
# /tools 和 tools/list 会把这些信息返回给调用方，便于发现工具能力。
@dataclass(slots=True)
class ToolSpec:
    # name 是工具名，必须与 handle 函数中的分支匹配。
    name: str
    # description 是工具用途说明。
    description: str
    # input_schema 描述工具输入 JSON 结构。
    input_schema: JsonDict
    # output_schema 描述工具输出 JSON 结构。
    output_schema: JsonDict
    # examples 保存调用示例。
    examples: list[JsonDict]

    # 函数作用：
    # 将 ToolSpec 转成普通字典，方便 JSON 序列化。
    #
    # 返回值：
    # - 返回 JsonDict。
    def to_dict(self) -> JsonDict:
        # asdict 是 dataclasses 提供的递归转换函数。
        return asdict(self)


# 函数作用：
# 要求 payload 中某个字段是字符串。
#
# 参数说明：
# - payload：工具入参。
# - key：字段名。
# - default：字段缺失时使用的默认值。
#
# 返回值：
# - 返回字符串值。
def require_str(payload: JsonDict, key: str, default: str | None = None) -> str:
    # payload.get 支持缺失字段时使用默认值。
    value = payload.get(key, default)
    # None 或非字符串都视为参数错误。
    if value is None or not isinstance(value, str):
        raise ToolError(f"`{key}` must be a string", data={"field": key})
    return value


# 函数作用：
# 要求 payload 中某个字段是 JSON 对象。
#
# 参数说明：
# - payload：工具入参。
# - key：字段名。
# - default：字段缺失时使用的默认对象。
#
# 返回值：
# - 返回 dict。
def require_object(payload: JsonDict, key: str, default: JsonDict | None = None) -> JsonDict:
    # default or {} 确保缺省值是对象。
    value = payload.get(key, default or {})
    # 非 dict 时抛 ToolError。
    if not isinstance(value, dict):
        raise ToolError(f"`{key}` must be an object", data={"field": key})
    return value


# 函数作用：
# 读取可选数字列表，并把 int/float 统一转成 float。
#
# 参数说明：
# - payload：工具入参。
# - key：字段名。
# - default：字段缺失时的默认列表。
#
# 返回值：
# - 返回 list[float]。
def optional_number_list(payload: JsonDict, key: str, default: list[float] | None = None) -> list[float]:
    # 字段缺失时使用 default 或空列表。
    value = payload.get(key, default or [])
    # 必须是数组/list。
    if not isinstance(value, list):
        raise ToolError(f"`{key}` must be an array of numbers", data={"field": key})
    # numbers 保存转换后的 float 值。
    numbers: list[float] = []
    for item in value:
        # Python 3.10 的 int | float 写法用于 isinstance 的联合类型判断。
        if not isinstance(item, int | float):
            raise ToolError(f"`{key}` must contain only numbers", data={"field": key})
        # 统一转 float，便于向量计算。
        numbers.append(float(item))
    return numbers


# 函数作用：
# 启动一个 HTTP MCP Server。
#
# 参数说明：
# - name：服务名称，例如 embedding-mcp。
# - port：监听端口。
# - tools：工具元数据列表。
# - handler：具体工具处理函数。
# - config：服务配置，会在 /health 中返回。
#
# 返回值：
# - 无返回；serve_forever 会阻塞进程。
def run_server(
    name: str,
    port: int,
    tools: list[ToolSpec],
    handler: ToolHandler,
    config: JsonDict | None = None,
) -> None:
    # tool_map 用于快速判断工具名是否存在。
    tool_map = {tool.name: tool for tool in tools}
    # config 为空时用空字典，避免 JSON 响应中出现 None。
    config = config or {}

    # 类作用：
    # RequestHandler 是标准库 HTTPServer 的请求处理类。
    # 它处理健康检查、工具列表和 JSON-RPC 调用。
    class RequestHandler(BaseHTTPRequestHandler):
        # server_version 会出现在 HTTP Server header 中。
        server_version = f"{name}/0.2"

        # 函数作用：
        # 处理 GET 请求。
        #
        # 支持路径：
        # - /health：返回服务状态。
        # - /tools：返回工具列表。
        def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
            # /health 用于 docker-compose 或人工检查服务是否启动。
            if self.path == "/health":
                self._write_json({"status": "ok", "server": name, "config": config})
                return
            # /tools 用于查看当前 MCP Server 暴露哪些工具。
            if self.path == "/tools":
                self._write_json({"server": name, "tools": [tool.to_dict() for tool in tools]})
                return
            # 其他路径返回 404。
            self._write_json({"error": {"message": "not_found", "path": self.path}}, status=404)

        # 函数作用：
        # 处理 POST 请求。
        #
        # 支持路径：
        # - /rpc：标准 JSON-RPC MCP 调用。
        # - /call：兼容旧格式调用。
        def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
            try:
                # 读取并解析 JSON 请求体。
                payload = self._read_json()
                # /rpc 是 Python Agent JsonRpcMcpTransport 使用的标准路径。
                if self.path == "/rpc":
                    self._handle_json_rpc(payload)
                    return
                # /call 是兼容旧版测试或手工调用的简单接口。
                if self.path == "/call":
                    self._handle_legacy_call(payload)
                    return
                self._write_json({"error": {"message": "not_found", "path": self.path}}, status=404)
            except ToolError as exc:
                # 工具参数或业务错误转换为 JSON-RPC error。
                self._write_json(_json_rpc_error(None, exc.code, exc.message, exc.data), status=400)
            except json.JSONDecodeError as exc:
                # JSON 解析失败使用 JSON-RPC 标准 parse error code。
                self._write_json(_json_rpc_error(None, -32700, "invalid JSON body", {"detail": str(exc)}), status=400)
            except Exception as exc:  # pragma: no cover - defensive server boundary
                # 兜底捕获，避免服务因未预期异常退出。
                self._write_json(_json_rpc_error(None, -32603, "internal server error", {"detail": str(exc)}), status=500)

        # 函数作用：
        # 覆盖默认 HTTP 日志输出，避免测试环境刷屏。
        def log_message(self, format: str, *args: object) -> None:
            return

        # 函数作用：
        # 处理标准 JSON-RPC 请求。
        #
        # 参数说明：
        # - payload：请求体字典。
        def _handle_json_rpc(self, payload: JsonDict) -> None:
            # JSON-RPC id 原样回传，方便调用方匹配请求响应。
            request_id = payload.get("id")
            # 校验 jsonrpc 版本。
            if payload.get("jsonrpc") != "2.0":
                self._write_json(_json_rpc_error(request_id, -32600, "`jsonrpc` must be `2.0`"), status=400)
                return
            # method 决定是列工具还是调用工具。
            method = payload.get("method")
            if method == "tools/list":
                self._write_json(_json_rpc_result(request_id, {"tools": [tool.to_dict() for tool in tools]}))
                return
            if method != "tools/call":
                self._write_json(_json_rpc_error(request_id, -32601, f"unknown method `{method}`"), status=404)
                return
            # params 必须是对象。
            params = payload.get("params", {})
            if not isinstance(params, dict):
                self._write_json(_json_rpc_error(request_id, -32602, "`params` must be an object"), status=400)
                return
            # tools/call 使用 params.name 和 params.arguments。
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(tool_name, str):
                self._write_json(_json_rpc_error(request_id, -32602, "`params.name` must be a string"), status=400)
                return
            if not isinstance(arguments, dict):
                self._write_json(_json_rpc_error(request_id, -32602, "`params.arguments` must be an object"), status=400)
                return
            # 执行工具并写 JSON-RPC result。
            self._write_json(_json_rpc_result(request_id, _call_tool(tool_name, arguments)))

        # 函数作用：
        # 处理旧版 /call 请求。
        #
        # 参数说明：
        # - payload：请求体字典，格式为 {"tool": "...", "input": {...}}。
        def _handle_legacy_call(self, payload: JsonDict) -> None:
            # 旧格式工具名字段是 tool。
            tool_name = payload.get("tool")
            # 旧格式参数字段是 input。
            arguments = payload.get("input", {})
            if not isinstance(tool_name, str):
                self._write_json({"ok": False, "error": {"message": "`tool` must be a string"}}, status=400)
                return
            if not isinstance(arguments, dict):
                self._write_json({"ok": False, "error": {"message": "`input` must be an object"}}, status=400)
                return
            # 返回简单 ok/result 结构，便于 curl 手工测试。
            self._write_json({"ok": True, "server": name, "tool": tool_name, "result": _call_tool(tool_name, arguments)})

        # 函数作用：
        # 读取 HTTP 请求体并解析为 JSON 对象。
        #
        # 返回值：
        # - 返回 JsonDict。
        def _read_json(self) -> JsonDict:
            # Content-Length 决定读取多少字节。
            length = int(self.headers.get("Content-Length", "0"))
            # 没有请求体时按空 JSON 对象处理。
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(raw or "{}")
            # 顶层必须是 JSON object。
            if not isinstance(payload, dict):
                raise ToolError("JSON body must be an object", code=-32600)
            return payload

        # 函数作用：
        # 写 JSON HTTP 响应。
        #
        # 参数说明：
        # - value：响应对象。
        # - status：HTTP 状态码。
        def _write_json(self, value: JsonDict, status: int = 200) -> None:
            # sort_keys=True 让测试和日志输出稳定。
            body = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
            # 写状态码和响应头。
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            # 写响应体字节。
            self.wfile.write(body)

    # 函数作用：
    # 校验工具名并调用具体 server.py 传入的 handler。
    #
    # 参数说明：
    # - tool_name：工具名。
    # - arguments：工具参数。
    #
    # 返回值：
    # - 返回 JSON-RPC result 中的 result 对象。
    def _call_tool(tool_name: str, arguments: JsonDict) -> JsonDict:
        # 未注册工具返回 JSON-RPC method not found。
        if tool_name not in tool_map:
            raise ToolError(f"unknown tool `{tool_name}`", code=-32601, data={"tool": tool_name})
        # tool_call_id 为每次工具调用生成唯一 id，方便日志追踪。
        return {
            "tool_call_id": uuid4().hex,
            "server": name,
            "tool": tool_name,
            # output 是具体 MCP 工具的业务输出。
            "output": handler(tool_name, arguments),
        }

    # 创建 HTTPServer，监听所有网卡。
    httpd = HTTPServer(("0.0.0.0", port), RequestHandler)
    print(f"{name} listening on 0.0.0.0:{port}")
    # 阻塞运行，直到进程被终止。
    httpd.serve_forever()


# 函数作用：
# 构造 JSON-RPC 成功响应。
def _json_rpc_result(request_id: object, result: JsonDict) -> JsonDict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


# 函数作用：
# 构造 JSON-RPC 错误响应。
#
# 参数说明：
# - request_id：请求 id。
# - code：错误码。
# - message：错误消息。
# - data：附加错误信息。
def _json_rpc_error(request_id: object, code: int, message: str, data: JsonDict | None = None) -> JsonDict:
    # error 是 JSON-RPC 规定的错误对象。
    error: JsonDict = {"code": code, "message": message}
    # data 可选，有值时才写入。
    if data:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}
