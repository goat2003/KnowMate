from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import time
from typing import Any, Protocol
from uuid import uuid4

from jsonschema import ValidationError, validate

from app.contracts import JsonDict
from app.mcp.policy import MCPPolicy
from app.observability import METRICS, redact_sensitive


@dataclass(frozen=True, slots=True)
class McpToolDefinition:
    name: str
    description: str
    input_schema: JsonDict
    output_schema: JsonDict | None = None


class McpTransport(Protocol):
    transport_name: str

    def start(self) -> None: ...

    def close(self) -> None: ...

    def list_tools(self, server_name: str) -> dict[str, McpToolDefinition]: ...

    def get_tool(self, server_name: str, tool_name: str) -> McpToolDefinition | None: ...

    def call(self, server_name: str, tool_name: str, payload: JsonDict, request_id: str) -> JsonDict: ...


@dataclass(slots=True)
class McpCallResult:
    result: JsonDict
    log: JsonDict


def _tool(
    name: str,
    *,
    required_input: list[str] | None = None,
    input_properties: JsonDict | None = None,
    required_output: list[str] | None = None,
    output_properties: JsonDict | None = None,
) -> McpToolDefinition:
    return McpToolDefinition(
        name=name,
        description=f"In-memory development implementation of {name}.",
        input_schema={
            "type": "object",
            "required": required_input or [],
            "properties": input_properties or {},
        },
        output_schema={
            "type": "object",
            "required": required_output or [],
            "properties": output_properties or {},
        },
    )


_STRING = {"type": "string"}
_ARRAY = {"type": "array"}
_OBJECT = {"type": "object"}
_BOOLEAN = {"type": "boolean"}
_INTEGER = {"type": "integer"}

MEMORY_TOOLS: dict[str, dict[str, McpToolDefinition]] = {
    "embedding-mcp": {
        "embed_text": _tool(
            "embed_text",
            required_input=["text"],
            input_properties={"text": _STRING, "metadata": _OBJECT},
            required_output=["embedding", "dim"],
            output_properties={"embedding": _ARRAY, "dim": _INTEGER},
        ),
        "embed_batch": _tool(
            "embed_batch",
            required_input=["texts"],
            input_properties={"texts": _ARRAY, "metadata": _OBJECT},
            required_output=["embeddings", "dim"],
            output_properties={"embeddings": _ARRAY, "dim": _INTEGER},
        ),
    },
    "fetch-mcp": {
        "fetch_webpage": _tool(
            "fetch_webpage",
            required_input=["url"],
            input_properties={"url": _STRING},
            required_output=["raw_text"],
            output_properties={"title": _STRING, "raw_text": _STRING},
        ),
        "extract_main_content": _tool(
            "extract_main_content",
            required_input=["html"],
            input_properties={"html": _STRING},
            required_output=["raw_text"],
            output_properties={"raw_text": _STRING},
        ),
        "clean_html": _tool(
            "clean_html",
            required_input=["html"],
            input_properties={"html": _STRING},
            required_output=["html"],
            output_properties={"html": _STRING},
        ),
        "check_url_alive": _tool(
            "check_url_alive",
            required_input=["url"],
            input_properties={"url": _STRING},
            required_output=["alive", "status_code"],
            output_properties={"alive": _BOOLEAN, "status_code": _INTEGER},
        ),
    },
    "milvus-mcp": {
        "insert_memory_vector": _tool(
            "insert_memory_vector",
            required_input=["embedding"],
            input_properties={"id": _STRING, "embedding": _ARRAY, "metadata": _OBJECT},
            required_output=["upserted", "id"],
            output_properties={"upserted": _BOOLEAN, "id": _STRING},
        ),
        "batch_insert_memory_vectors": _tool(
            "batch_insert_memory_vectors",
            required_input=["items"],
            input_properties={"items": _ARRAY},
            required_output=["upserted_count", "ids"],
            output_properties={"upserted_count": _INTEGER, "ids": _ARRAY},
        ),
        "search_similar_memory": _tool(
            "search_similar_memory",
            required_input=["embedding"],
            input_properties={
                "embedding": _ARRAY,
                "limit": _INTEGER,
                "minimum_score": {"type": "number"},
                "metadata_filter": _OBJECT,
            },
            required_output=["matches"],
            output_properties={"matches": _ARRAY},
        ),
        "search_related_articles": _tool(
            "search_related_articles",
            required_input=["embedding"],
            input_properties={"embedding": _ARRAY, "limit": _INTEGER},
            required_output=["matches"],
            output_properties={"matches": _ARRAY},
        ),
        "search_articles": _tool(
            "search_articles",
            input_properties={"topic": _STRING, "limit": _INTEGER},
            required_output=["matches"],
            output_properties={"matches": _ARRAY},
        ),
        "semantic_deduplicate": _tool(
            "semantic_deduplicate",
            required_input=["items"],
            input_properties={"items": _ARRAY, "threshold": {"type": "number"}},
            required_output=["unique_items"],
            output_properties={"unique_items": _ARRAY, "duplicates": _ARRAY},
        ),
        "delete_memory_vectors": _tool(
            "delete_memory_vectors",
            input_properties={"ids": _ARRAY, "metadata_filter": _OBJECT},
            required_output=["deleted_count"],
            output_properties={"deleted_count": _INTEGER, "ids": _ARRAY},
        ),
    },
    "neo4j-mcp": {
        "query_user_interest_graph": _tool(
            "query_user_interest_graph",
            required_input=["user_id"],
            input_properties={"user_id": _STRING, "snapshot": _OBJECT},
            required_output=["topics"],
            output_properties={"topics": _ARRAY, "user_id": _STRING},
        ),
        "update_user_interest_graph": _tool(
            "update_user_interest_graph",
            required_input=["user_id"],
            input_properties={
                "user_id": _STRING,
                "snapshot": _OBJECT,
                "extracted_feedback": _ARRAY,
                "sentiment": _STRING,
                "event_id": _STRING,
            },
            required_output=["updated"],
            output_properties={"updated": _BOOLEAN},
        ),
        "get_related_topics": _tool(
            "get_related_topics",
            required_input=["topic"],
            input_properties={"topic": _STRING, "limit": _INTEGER},
            required_output=["topics"],
            output_properties={"topics": _ARRAY},
        ),
        "explain_recommendation": _tool(
            "explain_recommendation",
            required_input=["user_id", "article"],
            input_properties={"user_id": _STRING, "article": _OBJECT},
            required_output=["reasons"],
            output_properties={"reasons": _ARRAY},
        ),
    },
}


class MemoryMcpTransport:
    transport_name = "memory"

    def __init__(self) -> None:
        self._tools = MEMORY_TOOLS

    def start(self) -> None:
        return

    def close(self) -> None:
        return

    def list_tools(self, server_name: str) -> dict[str, McpToolDefinition]:
        return self._tools.get(server_name, {})

    def get_tool(self, server_name: str, tool_name: str) -> McpToolDefinition | None:
        return self.list_tools(server_name).get(tool_name)

    def call(self, server_name: str, tool_name: str, payload: JsonDict, request_id: str) -> JsonDict:
        if self.get_tool(server_name, tool_name) is None:
            raise RuntimeError(f"Unknown memory MCP tool `{server_name}.{tool_name}`")
        if server_name == "embedding-mcp":
            if tool_name == "embed_batch":
                return {"embeddings": [self._embedding(str(text)) for text in payload.get("texts", [])], "dim": 3}
            return {"embedding": self._embedding(str(payload.get("text", ""))), "dim": 3}
        if server_name == "milvus-mcp":
            if tool_name == "insert_memory_vector":
                memory_id = str(payload.get("id") or hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())
                return {"upserted": True, "id": memory_id}
            if tool_name == "batch_insert_memory_vectors":
                items = payload.get("items", [])
                ids = [
                    str(item.get("id") or hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest())
                    for item in items
                    if isinstance(item, dict)
                ]
                return {"upserted_count": len(ids), "ids": ids}
            if tool_name == "delete_memory_vectors":
                return {"deleted_count": len(payload.get("ids", [])), "ids": payload.get("ids", [])}
            if tool_name == "semantic_deduplicate":
                return {"unique_items": payload.get("items", []), "duplicates": []}
            return {"matches": [{"article_id": "memory-related-1", "score": 0.81}]}
        if server_name == "neo4j-mcp":
            if tool_name == "update_user_interest_graph":
                return {"updated": True, "profile_patch": payload}
            if tool_name == "get_related_topics":
                return {"topics": [{"name": "AI", "score": 0.9}]}
            if tool_name == "explain_recommendation":
                return {"reasons": ["memory fallback"], "score": 0.5}
            return {"topics": ["AI", "knowledge-management", "engineering"], "user_id": payload.get("user_id", "")}
        if server_name == "fetch-mcp":
            if tool_name == "check_url_alive":
                return {"alive": bool(payload.get("url")), "status_code": 200 if payload.get("url") else 0}
            if tool_name == "extract_main_content":
                return {"raw_text": str(payload.get("html", ""))}
            if tool_name == "clean_html":
                return {"html": str(payload.get("html", "")).replace("<script>", "").replace("</script>", "")}
            return {"title": "Memory fetched document", "raw_text": "This text was fetched by memory fallback."}
        raise RuntimeError(f"Unknown memory MCP server `{server_name}`")

    def _embedding(self, text: str) -> list[float]:
        return [round((len(text) % 13) / 13, 4), 0.37, 0.61]


# Backward-compatible development name used by existing tests and callers.
MockMcpTransport = MemoryMcpTransport


class BaseMcpClient:
    server_name = "mcp"

    def __init__(
        self,
        transport: McpTransport,
        policy: MCPPolicy | None = None,
        *,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.1,
        circuit_failure_threshold: int = 3,
        circuit_reset_seconds: float = 30.0,
        fallback_transport: McpTransport | None = None,
    ) -> None:
        self.transport = transport
        self.policy = policy or MCPPolicy()
        self.max_retries = max(int(max_retries), 0)
        self.retry_backoff_seconds = max(float(retry_backoff_seconds), 0)
        self.circuit_failure_threshold = max(int(circuit_failure_threshold), 1)
        self.circuit_reset_seconds = max(float(circuit_reset_seconds), 0)
        self.fallback_transport = fallback_transport
        self._consecutive_failures = 0
        self._circuit_opened_at = 0.0

    def call_tool(self, tool_name: str, payload: JsonDict, *, agent_name: str, run_id: str) -> McpCallResult:
        started = time.perf_counter()
        call_id = uuid4().hex
        request_payload: JsonDict = {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": payload},
        }

        decision = self.policy.check(agent_name, tool_name)
        if not decision.allowed:
            return self._error_result(
                code="MCP_PERMISSION_DENIED",
                message=decision.error_message,
                status="denied",
                request_payload=request_payload,
                run_id=run_id,
                agent_name=agent_name,
                tool_name=tool_name,
                started=started,
                attempts=0,
            )

        tool = self.transport.get_tool(self.server_name, tool_name)
        if tool is None and self.fallback_transport is not None:
            tool = self.fallback_transport.get_tool(self.server_name, tool_name)
        if tool is not None:
            try:
                validate(instance=payload, schema=tool.input_schema)
            except ValidationError as exc:
                return self._error_result(
                    code="MCP_INPUT_SCHEMA_INVALID",
                    message=exc.message,
                    status="invalid_input",
                    request_payload=request_payload,
                    run_id=run_id,
                    agent_name=agent_name,
                    tool_name=tool_name,
                    started=started,
                    attempts=0,
                )

        if self._is_circuit_open():
            if self.fallback_transport is not None:
                try:
                    result = self.fallback_transport.call(self.server_name, tool_name, payload, call_id)
                    self._validate_output(self.fallback_transport.get_tool(self.server_name, tool_name), result)
                    return self._success_result(
                        result=result,
                        status="degraded",
                        request_payload=request_payload,
                        run_id=run_id,
                        agent_name=agent_name,
                        tool_name=tool_name,
                        started=started,
                        attempts=0,
                        error_message=f"MCP circuit open for `{self.server_name}`",
                        fallback=getattr(self.fallback_transport, "transport_name", "fallback"),
                    )
                except Exception:
                    pass
            return self._error_result(
                code="MCP_CIRCUIT_OPEN",
                message=f"MCP circuit open for `{self.server_name}`",
                status="circuit_open",
                request_payload=request_payload,
                run_id=run_id,
                agent_name=agent_name,
                tool_name=tool_name,
                started=started,
                attempts=0,
            )

        attempts = 0
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            attempts = attempt + 1
            try:
                result = self.transport.call(self.server_name, tool_name, payload, call_id)
                self._validate_output(tool, result)
                self._consecutive_failures = 0
                return self._success_result(
                    result=result,
                    status="success",
                    request_payload=request_payload,
                    run_id=run_id,
                    agent_name=agent_name,
                    tool_name=tool_name,
                    started=started,
                    attempts=attempts,
                )
            except ValidationError as exc:
                return self._error_result(
                    code="MCP_OUTPUT_SCHEMA_INVALID",
                    message=exc.message,
                    status="failed",
                    request_payload=request_payload,
                    run_id=run_id,
                    agent_name=agent_name,
                    tool_name=tool_name,
                    started=started,
                    attempts=attempts,
                )
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries and self.retry_backoff_seconds:
                    time.sleep(self.retry_backoff_seconds * (2**attempt))

        self._record_failure()
        if self.fallback_transport is not None:
            try:
                fallback_tool = self.fallback_transport.get_tool(self.server_name, tool_name)
                result = self.fallback_transport.call(self.server_name, tool_name, payload, call_id)
                self._validate_output(fallback_tool, result)
                return self._success_result(
                    result=result,
                    status="degraded",
                    request_payload=request_payload,
                    run_id=run_id,
                    agent_name=agent_name,
                    tool_name=tool_name,
                    started=started,
                    attempts=attempts,
                    error_message=str(last_error or ""),
                    fallback=getattr(self.fallback_transport, "transport_name", "fallback"),
                )
            except Exception as fallback_error:
                last_error = RuntimeError(f"{last_error}; fallback failed: {fallback_error}")

        return self._error_result(
            code="MCP_CALL_FAILED",
            message=str(last_error or "MCP call failed"),
            status="failed",
            request_payload=request_payload,
            run_id=run_id,
            agent_name=agent_name,
            tool_name=tool_name,
            started=started,
            attempts=attempts,
        )

    def _validate_output(self, tool: McpToolDefinition | None, result: JsonDict) -> None:
        if tool is not None and tool.output_schema:
            validate(instance=result, schema=tool.output_schema)

    def _is_circuit_open(self) -> bool:
        if not self._circuit_opened_at:
            return False
        if time.monotonic() - self._circuit_opened_at >= self.circuit_reset_seconds:
            self._circuit_opened_at = 0.0
            self._consecutive_failures = 0
            return False
        return True

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.circuit_failure_threshold:
            self._circuit_opened_at = time.monotonic()

    def _success_result(
        self,
        *,
        result: JsonDict,
        status: str,
        request_payload: JsonDict,
        run_id: str,
        agent_name: str,
        tool_name: str,
        started: float,
        attempts: int,
        error_message: str = "",
        fallback: str = "",
    ) -> McpCallResult:
        response_payload: JsonDict = {"jsonrpc": "2.0", "id": request_payload["id"], "result": result}
        return self._result(
            result=result,
            request_payload=request_payload,
            response_payload=response_payload,
            run_id=run_id,
            agent_name=agent_name,
            tool_name=tool_name,
            success=True,
            status=status,
            error_message=error_message,
            latency_ms=int((time.perf_counter() - started) * 1000),
            attempts=attempts,
            fallback=fallback,
        )

    def _error_result(
        self,
        *,
        code: str,
        message: str,
        status: str,
        request_payload: JsonDict,
        run_id: str,
        agent_name: str,
        tool_name: str,
        started: float,
        attempts: int,
    ) -> McpCallResult:
        result: JsonDict = {"error": {"code": code, "message": message}}
        response_payload: JsonDict = {"jsonrpc": "2.0", "id": request_payload["id"], "error": result["error"]}
        return self._result(
            result=result,
            request_payload=request_payload,
            response_payload=response_payload,
            run_id=run_id,
            agent_name=agent_name,
            tool_name=tool_name,
            success=False,
            status=status,
            error_message=message,
            latency_ms=int((time.perf_counter() - started) * 1000),
            attempts=attempts,
            fallback="",
        )

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
        attempts: int,
        fallback: str,
    ) -> McpCallResult:
        METRICS.record_mcp_tool(self.server_name, tool_name, status, latency_ms / 1000)
        return McpCallResult(
            result=result,
            log={
                "run_id": run_id,
                "call_id": str(request_payload.get("id", "")),
                "agent_name": agent_name,
                "server_name": self.server_name,
                "tool_name": tool_name,
                "request_json": json.dumps(redact_sensitive(request_payload), ensure_ascii=False),
                "response_json": json.dumps(redact_sensitive(response_payload), ensure_ascii=False),
                "status": status,
                "error_message": redact_sensitive(error_message),
                "success": success,
                "latency_ms": latency_ms,
                "attempts": attempts,
                "fallback": fallback,
            },
        )
