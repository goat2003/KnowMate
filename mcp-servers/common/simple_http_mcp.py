from __future__ import annotations

from dataclasses import dataclass, asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from typing import Callable, Any
from uuid import uuid4


JsonDict = dict[str, Any]
ToolHandler = Callable[[str, JsonDict], JsonDict]


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


def run_server(
    name: str,
    port: int,
    tools: list[ToolSpec],
    handler: ToolHandler,
    config: JsonDict | None = None,
) -> None:
    tool_map = {tool.name: tool for tool in tools}
    config = config or {}

    class RequestHandler(BaseHTTPRequestHandler):
        server_version = f"{name}/0.2"

        def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
            if self.path == "/health":
                self._write_json({"status": "ok", "server": name, "config": config})
                return
            if self.path == "/tools":
                self._write_json({"server": name, "tools": [tool.to_dict() for tool in tools]})
                return
            self._write_json({"error": {"message": "not_found", "path": self.path}}, status=404)

        def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
            try:
                payload = self._read_json()
                if self.path == "/rpc":
                    self._handle_json_rpc(payload)
                    return
                if self.path == "/call":
                    self._handle_legacy_call(payload)
                    return
                self._write_json({"error": {"message": "not_found", "path": self.path}}, status=404)
            except ToolError as exc:
                self._write_json(_json_rpc_error(None, exc.code, exc.message, exc.data), status=400)
            except json.JSONDecodeError as exc:
                self._write_json(_json_rpc_error(None, -32700, "invalid JSON body", {"detail": str(exc)}), status=400)
            except Exception as exc:  # pragma: no cover - defensive server boundary
                self._write_json(_json_rpc_error(None, -32603, "internal server error", {"detail": str(exc)}), status=500)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _handle_json_rpc(self, payload: JsonDict) -> None:
            request_id = payload.get("id")
            if payload.get("jsonrpc") != "2.0":
                self._write_json(_json_rpc_error(request_id, -32600, "`jsonrpc` must be `2.0`"), status=400)
                return
            method = payload.get("method")
            if method == "tools/list":
                self._write_json(_json_rpc_result(request_id, {"tools": [tool.to_dict() for tool in tools]}))
                return
            if method != "tools/call":
                self._write_json(_json_rpc_error(request_id, -32601, f"unknown method `{method}`"), status=404)
                return
            params = payload.get("params", {})
            if not isinstance(params, dict):
                self._write_json(_json_rpc_error(request_id, -32602, "`params` must be an object"), status=400)
                return
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(tool_name, str):
                self._write_json(_json_rpc_error(request_id, -32602, "`params.name` must be a string"), status=400)
                return
            if not isinstance(arguments, dict):
                self._write_json(_json_rpc_error(request_id, -32602, "`params.arguments` must be an object"), status=400)
                return
            self._write_json(_json_rpc_result(request_id, _call_tool(tool_name, arguments)))

        def _handle_legacy_call(self, payload: JsonDict) -> None:
            tool_name = payload.get("tool")
            arguments = payload.get("input", {})
            if not isinstance(tool_name, str):
                self._write_json({"ok": False, "error": {"message": "`tool` must be a string"}}, status=400)
                return
            if not isinstance(arguments, dict):
                self._write_json({"ok": False, "error": {"message": "`input` must be an object"}}, status=400)
                return
            self._write_json({"ok": True, "server": name, "tool": tool_name, "result": _call_tool(tool_name, arguments)})

        def _read_json(self) -> JsonDict:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(raw or "{}")
            if not isinstance(payload, dict):
                raise ToolError("JSON body must be an object", code=-32600)
            return payload

        def _write_json(self, value: JsonDict, status: int = 200) -> None:
            body = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def _call_tool(tool_name: str, arguments: JsonDict) -> JsonDict:
        if tool_name not in tool_map:
            raise ToolError(f"unknown tool `{tool_name}`", code=-32601, data={"tool": tool_name})
        return {
            "tool_call_id": uuid4().hex,
            "server": name,
            "tool": tool_name,
            "output": handler(tool_name, arguments),
        }

    httpd = HTTPServer(("0.0.0.0", port), RequestHandler)
    print(f"{name} listening on 0.0.0.0:{port}")
    httpd.serve_forever()


def _json_rpc_result(request_id: object, result: JsonDict) -> JsonDict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _json_rpc_error(request_id: object, code: int, message: str, data: JsonDict | None = None) -> JsonDict:
    error: JsonDict = {"code": code, "message": message}
    if data:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}
