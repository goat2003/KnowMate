from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any, Protocol
from urllib import request as urlrequest
from uuid import uuid4

from app.contracts import JsonDict
from app.mcp.policy import MCPPolicy


class McpTransport(Protocol):
    def call(self, server_name: str, tool_name: str, payload: JsonDict) -> JsonDict:
        ...


@dataclass(slots=True)
class McpCallResult:
    result: JsonDict
    log: JsonDict


class MockMcpTransport:
    def call(self, server_name: str, tool_name: str, payload: JsonDict) -> JsonDict:
        if server_name == "embedding-mcp":
            if tool_name == "embed_batch":
                embeddings = [self._embedding(str(text)) for text in payload.get("texts", [])]
                return {"embeddings": embeddings, "dim": 3}
            text = str(payload.get("text", ""))
            return {"embedding": self._embedding(text), "dim": 3}
        if server_name == "milvus-mcp":
            if tool_name == "semantic_deduplicate":
                return {"unique_items": payload.get("items", []), "duplicates": []}
            return {"matches": [{"article_id": "mock-related-1", "score": 0.81}]}
        if server_name == "neo4j-mcp":
            if tool_name in {"update_profile", "update_user_interest_graph"}:
                return {"updated": True, "profile_patch": payload}
            return {"topics": ["AI", "knowledge-management", "engineering"], "user_id": payload.get("user_id", "")}
        if server_name == "fetch-mcp":
            if tool_name == "check_url_alive":
                return {"alive": bool(payload.get("url")), "status_code": 200 if payload.get("url") else 0}
            if tool_name == "extract_main_content":
                return {"raw_text": str(payload.get("html", ""))}
            if tool_name == "clean_html":
                return {"html": str(payload.get("html", "")).replace("<script>", "").replace("</script>", "")}
            return {"title": "Mock fetched document", "raw_text": "This text was fetched by mock transport."}
        return {"ok": True}

    def _embedding(self, text: str) -> list[float]:
        return [round((len(text) % 13) / 13, 4), 0.37, 0.61]


class JsonRpcMcpTransport:
    def __init__(self, endpoints: dict[str, str]) -> None:
        self.endpoints = endpoints

    def call(self, server_name: str, tool_name: str, payload: JsonDict) -> JsonDict:
        base_url = self._endpoint(server_name).rstrip("/")
        request_payload = {
            "jsonrpc": "2.0",
            "id": uuid4().hex,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": payload},
        }
        body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
        req = urlrequest.Request(
            f"{base_url}/rpc",
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urlrequest.urlopen(req, timeout=8) as response:
            envelope = json.loads(response.read().decode("utf-8"))
        if "error" in envelope:
            message = envelope["error"].get("message", "MCP JSON-RPC error")
            raise RuntimeError(f"{server_name}.{tool_name}: {message}")
        result = envelope.get("result", {})
        if isinstance(result, dict) and isinstance(result.get("output"), dict):
            return result["output"]
        if isinstance(result, dict):
            return result
        raise RuntimeError(f"{server_name}.{tool_name}: invalid JSON-RPC result")

    def _endpoint(self, server_name: str) -> str:
        candidates = [
            server_name,
            server_name.replace("-mcp", ""),
            server_name.replace("-", "_"),
            server_name.replace("-mcp", "").replace("-", "_"),
        ]
        for key in candidates:
            if self.endpoints.get(key):
                return self.endpoints[key]
        raise RuntimeError(f"No MCP endpoint configured for `{server_name}`")


class BaseMcpClient:
    server_name = "mcp"

    def __init__(self, transport: McpTransport, policy: MCPPolicy | None = None) -> None:
        self.transport = transport
        self.policy = policy or MCPPolicy()

    def call_tool(self, tool_name: str, payload: JsonDict, *, agent_name: str, run_id: str) -> McpCallResult:
        started = time.perf_counter()
        request_payload = {
            "jsonrpc": "2.0",
            "id": uuid4().hex,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": payload},
        }
        success = False
        status = "failed"
        error_message = ""
        result: JsonDict

        decision = self.policy.check(agent_name, tool_name)
        if not decision.allowed:
            error_message = decision.error_message
            result = {"error": {"code": "MCP_PERMISSION_DENIED", "message": error_message}}
            response_payload: JsonDict = {
                "jsonrpc": "2.0",
                "error": {"code": "MCP_PERMISSION_DENIED", "message": error_message},
            }
            status = "denied"
            latency_ms = int((time.perf_counter() - started) * 1000)
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

        try:
            result = self.transport.call(self.server_name, tool_name, payload)
            response_payload: JsonDict = {"jsonrpc": "2.0", "result": result}
            success = True
            status = "success"
        except Exception as exc:  # pragma: no cover - real transport path
            error_message = str(exc)
            result = {"error": {"code": "MCP_CALL_FAILED", "message": error_message}}
            response_payload = {
                "jsonrpc": "2.0",
                "error": {"code": "MCP_CALL_FAILED", "message": error_message},
            }
            status = "failed"
        latency_ms = int((time.perf_counter() - started) * 1000)
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
        return McpCallResult(
            result=result,
            log={
                "run_id": run_id,
                "agent_name": agent_name,
                "server_name": self.server_name,
                "tool_name": tool_name,
                "request_json": json.dumps(request_payload, ensure_ascii=False),
                "response_json": json.dumps(response_payload, ensure_ascii=False),
                "status": status,
                "error_message": error_message,
                "success": success,
                "latency_ms": latency_ms,
            },
        )
