from __future__ import annotations

import asyncio
import contextvars
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import timedelta
import json
import logging
import os
from threading import Thread
from collections.abc import MutableMapping
from typing import Any

import httpx
from opentelemetry import context as otel_context_api
from opentelemetry import propagate

from app.config import McpServerSettings
from app.contracts import JsonDict
from app.mcp.base_client import McpToolDefinition, MemoryMcpTransport


LOGGER = logging.getLogger(__name__)
_request_otel_context: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "knowmate_mcp_request_otel_context",
    default=None,
)


@dataclass(slots=True)
class _Connection:
    stack: AsyncExitStack
    session: Any


class OfficialMcpTransport:
    transport_name = "official-sdk"

    def __init__(self, servers: dict[str, McpServerSettings], timeout_seconds: float = 8.0) -> None:
        self.servers = servers
        self.timeout_seconds = max(float(timeout_seconds), 0.1)
        self._memory = MemoryMcpTransport()
        self._tools: dict[str, dict[str, McpToolDefinition]] = {}
        self._connections: dict[str, _Connection] = {}
        self._connection_locks: dict[str, asyncio.Lock] = {}
        self._startup_errors: dict[str, str] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: Thread | None = None

    @property
    def startup_errors(self) -> dict[str, str]:
        return dict(self._startup_errors)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._loop = asyncio.new_event_loop()
        self._thread = Thread(target=self._run_loop, name="mcp-client-loop", daemon=True)
        self._thread.start()
        future = asyncio.run_coroutine_threadsafe(self._start_all(), self._loop)
        try:
            future.result(timeout=max(self.timeout_seconds + 2, 5))
        except Exception as exc:
            future.cancel()
            self._startup_errors["__manager__"] = str(exc)
            LOGGER.warning("MCP startup discovery did not complete: %s", exc)
        for server_name, error in self._startup_errors.items():
            LOGGER.warning("MCP server `%s` unavailable during startup discovery: %s", server_name, error)

    def close(self) -> None:
        if not self._loop or not self._thread:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(self._close_all(), self._loop)
            future.result(timeout=max(self.timeout_seconds + 2, 5))
        except Exception as exc:
            LOGGER.warning("MCP client shutdown cleanup failed: %s", exc)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=max(self.timeout_seconds + 2, 5))
            self._loop = None
            self._thread = None

    def list_tools(self, server_name: str) -> dict[str, McpToolDefinition]:
        config = self.servers.get(server_name)
        if config and config.transport == "memory":
            return self._memory.list_tools(server_name)
        return self._tools.get(server_name, {})

    def get_tool(self, server_name: str, tool_name: str) -> McpToolDefinition | None:
        return self.list_tools(server_name).get(tool_name)

    def call(self, server_name: str, tool_name: str, payload: JsonDict, request_id: str) -> JsonDict:
        config = self._server(server_name)
        if config.transport == "memory":
            return self._memory.call(server_name, tool_name, payload, request_id)
        self.start()
        assert self._loop is not None
        otel_context = otel_context_api.get_current()
        future = asyncio.run_coroutine_threadsafe(self._call(server_name, tool_name, payload, otel_context), self._loop)
        try:
            return future.result(timeout=self.timeout_seconds + 1)
        except TimeoutError:
            future.cancel()
            raise TimeoutError(f"MCP call timed out after {self.timeout_seconds}s: {server_name}.{tool_name}")

    def _inject_trace_headers(self, headers: MutableMapping[str, str], context: Any | None = None) -> None:
        propagate.inject(headers, context=context)

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _start_all(self) -> None:
        async def start_one(server_name: str, config: McpServerSettings) -> None:
            if config.transport == "memory":
                self._tools[server_name] = self._memory.list_tools(server_name)
                return
            try:
                await asyncio.wait_for(self._connect(server_name), timeout=self.timeout_seconds)
                self._startup_errors.pop(server_name, None)
            except asyncio.CancelledError as exc:
                self._startup_errors[server_name] = str(exc) or "startup cancelled"
            except Exception as exc:
                self._startup_errors[server_name] = str(exc) or type(exc).__name__

        await asyncio.gather(*(start_one(name, config) for name, config in self.servers.items()))

    async def _connect(self, server_name: str) -> _Connection:
        existing = self._connections.get(server_name)
        if existing is not None:
            return existing
        lock = self._connection_locks.setdefault(server_name, asyncio.Lock())
        async with lock:
            existing = self._connections.get(server_name)
            if existing is not None:
                return existing
            config = self._server(server_name)
            stack = AsyncExitStack()
            try:
                from mcp import ClientSession, StdioServerParameters
                from mcp.client.stdio import stdio_client
                from mcp.client.streamable_http import streamable_http_client

                if config.transport == "stdio":
                    if not config.command:
                        raise RuntimeError(f"Missing stdio command for `{server_name}`")
                    env = dict(os.environ)
                    env.update(config.env)
                    params = StdioServerParameters(command=config.command, args=config.args, env=env)
                    read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
                elif config.transport == "streamable_http":
                    if not config.url:
                        raise RuntimeError(f"Missing Streamable HTTP URL for `{server_name}`")
                    base_headers = dict(config.headers)

                    async def inject_trace_context(request: httpx.Request) -> None:
                        for key, value in base_headers.items():
                            if key not in request.headers:
                                request.headers[key] = value
                        self._inject_trace_headers(request.headers, context=_request_otel_context.get())

                    http_client = await stack.enter_async_context(
                        httpx.AsyncClient(
                            headers=base_headers or None,
                            timeout=self.timeout_seconds,
                            follow_redirects=True,
                            event_hooks={"request": [inject_trace_context]},
                        )
                    )
                    read_stream, write_stream, _ = await stack.enter_async_context(
                        streamable_http_client(config.url, http_client=http_client)
                    )
                else:
                    raise RuntimeError(f"Unsupported MCP transport `{config.transport}` for `{server_name}`")
                session = await stack.enter_async_context(
                    ClientSession(read_stream, write_stream, read_timeout_seconds=timedelta(seconds=self.timeout_seconds))
                )
                await session.initialize()
                connection = _Connection(stack=stack, session=session)
                self._connections[server_name] = connection
                self._tools[server_name] = await self._discover(session)
                return connection
            except BaseException:
                await stack.aclose()
                raise

    async def _discover(self, session: Any) -> dict[str, McpToolDefinition]:
        discovered: dict[str, McpToolDefinition] = {}
        cursor: str | None = None
        while True:
            page = await session.list_tools(cursor=cursor)
            for tool in page.tools:
                discovered[tool.name] = McpToolDefinition(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=dict(tool.inputSchema),
                    output_schema=dict(tool.outputSchema) if tool.outputSchema else None,
                )
            cursor = getattr(page, "nextCursor", None)
            if not cursor:
                return discovered

    async def _call(self, server_name: str, tool_name: str, payload: JsonDict, otel_context: Any | None) -> JsonDict:
        token = _request_otel_context.set(otel_context)
        try:
            connection = await self._connect(server_name)
            try:
                result = await connection.session.call_tool(
                    tool_name,
                    payload,
                    read_timeout_seconds=timedelta(seconds=self.timeout_seconds),
                )
                if result.isError:
                    messages = [getattr(content, "text", "") for content in result.content]
                    raise RuntimeError(
                        "; ".join(message for message in messages if message) or "MCP tool returned an error"
                    )
                if isinstance(result.structuredContent, dict):
                    return dict(result.structuredContent)
                for content in result.content:
                    text = getattr(content, "text", "")
                    if text:
                        parsed = json.loads(text)
                        if isinstance(parsed, dict):
                            return parsed
                raise RuntimeError(f"MCP tool `{server_name}.{tool_name}` returned no structured object")
            except Exception:
                await self._drop_connection(server_name)
                raise
        finally:
            _request_otel_context.reset(token)

    async def _drop_connection(self, server_name: str) -> None:
        connection = self._connections.pop(server_name, None)
        if connection is not None:
            await connection.stack.aclose()

    async def _close_all(self) -> None:
        for server_name in list(self._connections):
            try:
                await self._drop_connection(server_name)
            except Exception:
                pass
        self._connections.clear()

    def _server(self, server_name: str) -> McpServerSettings:
        config = self.servers.get(server_name)
        if config is None:
            raise RuntimeError(f"No MCP server configured for `{server_name}`")
        return config
