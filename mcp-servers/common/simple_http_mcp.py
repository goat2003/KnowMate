from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from typing import Any, Callable, Protocol

try:
    from common.observability import METRICS, record_tool
except ModuleNotFoundError:
    from observability import METRICS, record_tool


JsonDict = dict[str, Any]
ToolHandler = Callable[[str, JsonDict], JsonDict]
HealthProvider = Callable[[], JsonDict]


class Lifecycle(Protocol):
    def initialize(self) -> None: ...

    def close(self) -> None: ...


class ToolError(Exception):
    def __init__(self, message: str, code: int = -32000, data: JsonDict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.data = data or {}


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: JsonDict
    output_schema: JsonDict
    examples: list[JsonDict]

    def to_dict(self) -> JsonDict:
        return asdict(self)


def require_str(payload: JsonDict, key: str, default: str | None = None) -> str:
    value = payload.get(key, default)
    if value is None or not isinstance(value, str):
        raise ToolError(f"`{key}` must be a string", data={"field": key})
    return value


def require_object(payload: JsonDict, key: str, default: JsonDict | None = None) -> JsonDict:
    value = payload.get(key, default or {})
    if not isinstance(value, dict):
        raise ToolError(f"`{key}` must be an object", data={"field": key})
    return value


def optional_number_list(payload: JsonDict, key: str, default: list[float] | None = None) -> list[float]:
    value = payload.get(key, default or [])
    if not isinstance(value, list):
        raise ToolError(f"`{key}` must be an array of numbers", data={"field": key})
    numbers: list[float] = []
    for item in value:
        if not isinstance(item, int | float):
            raise ToolError(f"`{key}` must contain only numbers", data={"field": key})
        numbers.append(float(item))
    return numbers


def create_server(
    name: str,
    port: int,
    tools: list[ToolSpec],
    handler: ToolHandler,
    config: JsonDict | None = None,
    health_provider: HealthProvider | None = None,
):
    from mcp import types
    from mcp.server.fastmcp import FastMCP
    from starlette.requests import Request
    from starlette.responses import JSONResponse, PlainTextResponse

    config = config or {}
    server_name = name
    server = FastMCP(
        name,
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        port=port,
        streamable_http_path=os.getenv("MCP_HTTP_PATH", "/mcp"),
        json_response=True,
        stateless_http=True,
    )
    tool_map = {tool.name: tool for tool in tools}

    @server._mcp_server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=tool.name,
                description=tool.description,
                inputSchema=tool.input_schema,
                outputSchema=tool.output_schema,
            )
            for tool in tools
        ]

    @server._mcp_server.call_tool()
    async def call_tool(name: str, arguments: JsonDict) -> JsonDict:
        if name not in tool_map:
            raise ToolError(f"unknown tool `{name}`", code=-32601, data={"tool": name})
        return await record_tool(server_name, name, lambda: handler(name, arguments))

    @server.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_request: Request) -> JSONResponse:
        payload, status_code = build_health_payload(name, _transport(), config, health_provider)
        return JSONResponse(payload, status_code=status_code)

    @server.custom_route("/metrics", methods=["GET"], include_in_schema=False)
    async def metrics(_request: Request) -> PlainTextResponse:
        return PlainTextResponse(METRICS.render_text().decode("utf-8"), media_type="text/plain; version=0.0.4")

    return server


def run_server(
    name: str,
    port: int,
    tools: list[ToolSpec],
    handler: ToolHandler,
    config: JsonDict | None = None,
    health_provider: HealthProvider | None = None,
    lifecycle: Lifecycle | None = None,
) -> None:
    if lifecycle is not None:
        lifecycle.initialize()
    try:
        server = create_server(name, port, tools, handler, config, health_provider)
        server.run(transport=_transport())
    finally:
        if lifecycle is not None:
            lifecycle.close()


def build_health_payload(
    name: str,
    transport: str,
    config: JsonDict,
    health_provider: HealthProvider | None = None,
) -> tuple[JsonDict, int]:
    dependency = health_provider() if health_provider is not None else {"status": "healthy", "ready": True}
    ready = bool(dependency.get("ready", dependency.get("status") in {"healthy", "ok"}))
    return (
        {
            "status": "ok" if ready else "unhealthy",
            "server": name,
            "transport": transport,
            "config": config,
            "dependency": dependency,
        },
        200 if ready else 503,
    )


def _transport() -> str:
    transport = os.getenv("MCP_TRANSPORT", "streamable_http").strip().lower().replace("_", "-")
    if transport not in {"stdio", "streamable-http"}:
        raise RuntimeError(f"Unsupported MCP_TRANSPORT `{transport}`")
    return transport
