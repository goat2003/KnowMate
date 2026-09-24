"""Private, role-scoped memory adapter used by KnowMate.

This service intentionally exposes a small contract instead of Mem_Pro's
database APIs.  A production deployment can replace the repository with the
real MongoDB/Neo4j/Milvus implementation without changing the Go client.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
from mempro_backend import MemProBackend, MemProError
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROLE_RE = re.compile(r"^km_[0-9a-f]{40}$")
KEYS = {"interests", "goal", "avoid", "style", "level"}


class Repository:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS memories (
                role_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
                evidence TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(role_id, key))""")

    def list(self, role_id: str) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT key,value,evidence FROM memories WHERE role_id=? ORDER BY key", (role_id,)).fetchall()
        return [{"key": k, "value": v, "evidence": e} for k, v, e in rows]

    def build(self, role_id: str, dialogues: list[dict]) -> None:
        with self.lock, self.db:
            for dialogue in dialogues:
                text = str(dialogue.get("user", ""))
                for label, key in (("兴趣", "interests"), ("目标", "goal"), ("避开", "avoid"), ("风格", "style"), ("水平", "level")):
                    for prefix in (f"记住{label}：", f"记住{label}:"):
                        if text.startswith(prefix) and text[len(prefix):].strip():
                            value = text[len(prefix):].strip()[:500]
                            if key in {"interests", "avoid"}:
                                value = value.replace("，", ",").replace("、", ",")
                            self.db.execute("INSERT INTO memories(role_id,key,value,evidence) VALUES(?,?,?,?) ON CONFLICT(role_id,key) DO UPDATE SET value=excluded.value,evidence=excluded.evidence,updated_at=CURRENT_TIMESTAMP", (role_id, key, value, text[:500]))

    def delete(self, role_id: str, key: str) -> dict:
        with self.lock, self.db:
            if key:
                cursor = self.db.execute("DELETE FROM memories WHERE role_id=? AND key=?", (role_id, key))
            else:
                cursor = self.db.execute("DELETE FROM memories WHERE role_id=?", (role_id,))
        return {"deleted_count": int(cursor.rowcount if cursor.rowcount >= 0 else 0)}


def valid_role(role_id: object) -> bool:
    return isinstance(role_id, str) and bool(ROLE_RE.fullmatch(role_id))


class Handler(BaseHTTPRequestHandler):
    server_version = "KnowMateMemory/1.0"

    def _json(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        expected = os.environ.get("MEMORY_SERVICE_TOKEN", "")
        supplied = self.headers.get("Authorization", "")
        return bool(expected) and hmac.compare_digest(supplied, "Bearer " + expected)

    def _body(self) -> dict:
        size = min(int(self.headers.get("Content-Length", "0") or 0), 1 << 20)
        return json.loads(self.rfile.read(size) or b"{}")

    def _request(self, method: str) -> None:
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        try:
            body = self._body()
            role_id = body.get("role_id")
            if not valid_role(role_id):
                raise ValueError("invalid role_id")
            backend = self.server.backend
            if method == "retrieve":
                result = backend.retrieve(role_id, body.get("query", "")) if isinstance(backend, MemProBackend) else {"items": backend.list(role_id), "memory": {i["key"]: i["value"] for i in backend.list(role_id)}}
                self._json(200, {"ok": True, **result})
            elif method == "list":
                self._json(200, {"ok": True, "items": backend.list(role_id)})
            elif method == "build":
                dialogues = body.get("dialogues", [])
                if not isinstance(dialogues, list) or len(dialogues) > 20:
                    raise ValueError("invalid dialogues")
                backend.build(role_id, dialogues)
                self._json(200, {"ok": True, "items": backend.list(role_id)})
            elif method == "delete":
                key = body.get("key", "")
                if key and key not in KEYS:
                    raise ValueError("invalid key")
                deleted = backend.delete(role_id, key)
                self._json(200, {"ok": True, **(deleted if isinstance(deleted, dict) else {})})
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"ok": False, "error": str(exc)})
        except MemProError as exc:
            self._json(503, {"ok": False, "error": "memory backend unavailable"})
        except Exception:
            self._json(503, {"ok": False, "error": "memory backend unavailable"})

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/health":
            if not self._authorized():
                self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                return
            details = self.server.backend.health() if isinstance(self.server.backend, MemProBackend) else {"backend": "local", "dependencies": {"sqlite": "ready", "mongo": "not-configured", "neo4j": "not-configured", "milvus": "not-configured"}, "status": "ready"}
            code = 200 if details.get("status") in {"ready", "ok"} else 503
            self._json(code, {"status": details.get("status", "ready"), "memory": details})
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        paths = {"/memory/retrieve": "retrieve", "/memory/build": "build", "/memory/list": "list", "/memory/delete": "delete"}
        method = paths.get(urlparse(self.path).path)
        if method:
            self._request(method)
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def log_message(self, *_args) -> None:
        return


def serve(host: str | None = None, port: int | None = None) -> None:
    host = host or os.environ.get("MEMORY_SERVICE_HOST", "127.0.0.1")
    port = port or int(os.environ.get("MEMORY_SERVICE_PORT", "8091"))
    if host not in {"127.0.0.1", "localhost", "::1"} and os.environ.get("MEMORY_SERVICE_ALLOW_LAN") != "true":
        raise RuntimeError("memory service must bind loopback unless MEMORY_SERVICE_ALLOW_LAN=true")
    server = ThreadingHTTPServer((host, port), Handler)
    backend_mode = os.environ.get("MEMORY_BACKEND", "local").strip().lower()
    if backend_mode == "mem_pro":
        server.backend = MemProBackend()
    elif backend_mode == "local":
        server.backend = Repository(os.environ.get("MEMORY_SERVICE_DB", "memory-service/memory.sqlite3"))
    else:
        raise RuntimeError("MEMORY_BACKEND must be local or mem_pro")
    server.serve_forever()


if __name__ == "__main__":
    serve()
