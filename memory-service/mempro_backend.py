"""Restricted facade over the copied Mem_Pro runtime.

The original checkout is never imported from its D: drive path.  This module
loads only the read-only copy under memory-service/vendor/mem_pro and exposes
role-scoped operations to the private HTTP handler.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib
import io
import os
import re
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROLE_RE = re.compile(r"^km_[0-9a-f]{40}$")
ROLE_IN_TEXT_RE = re.compile(r"km_[0-9a-f]{40}", re.IGNORECASE)
KEYS = {"interests", "goal", "avoid", "style", "level"}
VENDOR = Path(__file__).resolve().parent / "vendor" / "mem_pro"


class MemProError(RuntimeError):
    pass


def _role(role_id: str) -> str:
    if not ROLE_RE.fullmatch(role_id or ""):
        raise MemProError("invalid role_id")
    return role_id


def _public_text(value: Any, limit: int) -> str:
    # Mem_Pro's model can include the analysis target in generated prose.
    # Strip internal identities before either a browser or the chat model sees it.
    return ROLE_IN_TEXT_RE.sub("当前用户", str(value or "")).strip()[:limit]


class _AsyncRunner:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._serve, name="mempro-async", daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()

    def close(self) -> None:
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2)
        self.loop.close()


class MemProBackend:
    def __init__(self) -> None:
        self._error = ""
        self._builder = None
        self._retriever = None
        self._user_store = None
        self._neo4j = None
        self._mongo = None
        self._milvus = None
        self._initialized = False
        # Capture Milvus settings before importing the copied Mem_Pro runtime.
        # Its settings module may populate MILVUS_URI with a container hostname.
        configured_uri = os.getenv("MILVUS_URI", "").strip()
        host = os.getenv("MILVUS_HOST", "127.0.0.1").strip()
        port = os.getenv("MILVUS_PORT", "19530").strip()
        self._milvus_uri = configured_uri or f"http://{host}:{port}"
        self._milvus_db_name = os.getenv("MILVUS_DB_NAME", "superCog").strip() or "superCog"
        self._milvus_token = os.getenv("MILVUS_TOKEN", "").strip()
        self._runner = _AsyncRunner()
        self._io_lock = threading.Lock()

    def _run(self, coro):
        runner = getattr(self, "_runner", None)
        return runner.run(coro) if runner is not None else asyncio.run(coro)

    def _run_quiet(self, coro):
        # The copied runtime prints raw dialogue and vectors. Keep that output
        # out of the HTTP service logs, which may be collected centrally.
        lock = getattr(self, "_io_lock", None)
        if lock is None:
            return self._run(coro)
        with lock, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return self._run(coro)

    def initialize(self) -> None:
        if self._initialized:
            return
        try:
            if not VENDOR.exists():
                raise MemProError("copied Mem_Pro runtime is missing")
            if str(VENDOR) not in sys.path:
                sys.path.insert(0, str(VENDOR))
            from main.final_main import BuildMain
            from app.memory.user_info_node.user_info_graph.user_info_store import UserInfoStore
            from app.common.manager.neo4j_manager import Neo4jManager
            self._builder = BuildMain()
            self._user_store = UserInfoStore()
            self._neo4j = Neo4jManager.get_instance()
            self._initialized = True
        except Exception as exc:
            self._error = f"Mem_Pro initialization failed: {exc.__class__.__name__}"
            raise MemProError(self._error) from exc

    def health(self) -> dict[str, Any]:
        details: dict[str, Any] = {"backend": "mem_pro", "vendor_copy": VENDOR.exists()}
        checks: dict[str, str] = {}
        try:
            self.initialize()
            checks["runtime"] = "ready"
        except MemProError:
            checks["runtime"] = "unavailable"
        checks["mongodb"] = self._ping_mongodb()
        checks["neo4j"] = self._ping_neo4j()
        checks["milvus"] = self._ping_milvus()
        checks["model"] = self._model_status()
        checks["embedding"] = self._embedding_status()
        details["dependencies"] = checks
        ready = all(value == "ready" for value in checks.values())
        details["status"] = "ready" if ready else "not_ready"
        details["error"] = self._error
        return details

    @staticmethod
    def _probe_openai_compatible(base_url: str, api_key: str) -> str:
        if not api_key.strip() or not base_url.strip():
            return "unconfigured"
        request = urllib.request.Request(
            base_url.rstrip("/") + "/models",
            headers={"Authorization": "Bearer " + api_key.strip(), "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return "ready" if 200 <= response.status < 300 else "unavailable"
        except (OSError, urllib.error.URLError, TimeoutError):
            return "unavailable"

    @staticmethod
    def _embedding_status() -> str:
        enabled = os.getenv("EMBEDDING_ENABLED", "true").strip().lower()
        if enabled in {"0", "false", "no", "off"}:
            return "disabled"
        return MemProBackend._probe_openai_compatible(
            os.getenv("EMBEDDING_BASE_URL", ""), os.getenv("EMBEDDING_API_KEY", "")
        )

    @staticmethod
    def _model_status() -> str:
        return MemProBackend._probe_openai_compatible(
            os.getenv("LLM_BASE_URL", ""), os.getenv("LLM_API_KEY", "")
        )

    def build(self, role_id: str, dialogues: list[dict[str, str]]) -> None:
        _role(role_id)
        if not isinstance(dialogues, list) or not dialogues or len(dialogues) > 20:
            raise MemProError("invalid dialogues")
        self.initialize()
        # BuildMain performs idempotent chunk/fact creation in Neo4j/Milvus and
        # updates the user profile. split=3 matches the Mem_Pro runtime default.
        self._run_quiet(self._builder.main(role_id=role_id, dialogues=dialogues, split=3, target_object=role_id))

    def retrieve(self, role_id: str, query: str) -> dict[str, Any]:
        _role(role_id)
        query = str(query or "").strip()
        if not query or len(query) > 4000:
            raise MemProError("invalid query")
        self.initialize()
        if self._retriever is None:
            from app.retrieval.retrieval_service import RetrievalService
            self._retriever = RetrievalService(
                embedding_client=None,
                use_llm_analyzer=False,
                mark_used=False,
                mark_used_mode="background",
            )
        result = self._run_quiet(self._retriever.retrieve(role_id=role_id, query_text=query, top_k=12, init_indexes=False, target_object=role_id))
        payload = result.to_dict() if hasattr(result, "to_dict") else {"result": str(result)}
        profile = {}
        if self._user_store is not None:
            try:
                profile = self._run_quiet(self._user_store.get_user_profile(role_id)) or {}
            except Exception:
                profile = {}
        # Keep the private contract small. Mem_Pro debug traces contain
        # database identifiers and routing internals that must not reach the
        # browser or the general-purpose agent prompt.
        evidence = []
        for item in payload.get("evidence_items", [])[:12]:
            if not isinstance(item, dict):
                continue
            content = _public_text(item.get("content"), 1200)
            if not content:
                continue
            evidence.append({
                "content": content[:1200],
                "source": _public_text(item.get("source"), 40),
                "score": float(item.get("final_score") or item.get("local_score") or 0),
            })
        prompt_context = _public_text(payload.get("prompt_context"), 6000)
        profile = {
            key: _public_text(profile.get(key), 500)
            for key in ("preference", "skill") if profile.get(key)
        }
        return {
            "memory": profile,
            "retrieval": {"prompt_context": prompt_context, "items": evidence},
            "items": [],
        }

    def list(self, role_id: str) -> list[dict[str, str]]:
        _role(role_id)
        self.initialize()
        if self._user_store is None:
            return []
        try:
            profile = self._run_quiet(self._user_store.get_user_profile(role_id)) or {}
        except ValueError:
            return []
        # Do not expose Mem_Pro's internal profile schema to ordinary users.
        # basic_info may contain identifying data, so it is intentionally not
        # returned through this user-facing memory list.
        items = []
        for source, key in (("preference", "interests"), ("skill", "level")):
            value = _public_text(profile.get(source), 500)
            if value:
                items.append({"key": key, "value": value, "evidence": "长期偏好画像"})
        return items

    def delete(self, role_id: str, key: str = "") -> dict[str, Any]:
        _role(role_id)
        if key and key not in KEYS:
            raise MemProError("invalid key")
        # Deletion is intentionally role-scoped in all three stores.  A key-level
        # delete is not supported by Mem_Pro's graph model, so it is rejected
        # instead of pretending that only one semantic fact was removed.
        if key:
            raise MemProError("Mem_Pro supports only delete-all for a role")
        self.initialize()
        deleted = {"mongodb": 0, "neo4j": 0, "milvus": 0}
        deleted["mongodb"] = self._delete_mongodb(role_id)
        deleted["neo4j"] = self._delete_neo4j(role_id)
        deleted["milvus"] = self._delete_milvus(role_id)
        return {"deleted": deleted}

    def _ping_mongodb(self) -> str:
        try:
            from pymongo import MongoClient
            uri = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017/")
            client = MongoClient(uri, serverSelectionTimeoutMS=500)
            client.admin.command("ping")
            client.close()
            return "ready"
        except Exception:
            return "unavailable"

    def _ping_neo4j(self) -> str:
        try:
            if self._neo4j is None:
                return "unavailable"
            # Neo4jManager wraps the driver and returns a boolean, unlike
            # the driver's verify_connectivity() which returns None.
            return "ready" if self._run(self._neo4j.verify_connectivity()) else "unavailable"
        except Exception:
            return "unavailable"

    def _ping_milvus(self) -> str:
        try:
            from pymilvus import connections
            host = os.getenv("MILVUS_HOST", "127.0.0.1")
            port = os.getenv("MILVUS_PORT", "19530")
            alias = "knowmate_mempro_health"
            connections.connect(alias, host=host, port=port, timeout=1)
            connections.disconnect(alias)
            return "ready"
        except Exception:
            return "unavailable"

    def _delete_mongodb(self, role_id: str) -> int:
        from pymongo import MongoClient
        client = MongoClient(os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017/"), serverSelectionTimeoutMS=1000)
        try:
            db = client[os.getenv("MONGODB_DB_NAME", "test_database")]
            total = 0
            for name in db.list_collection_names():
                total += int(db[name].delete_many({"role_id": role_id}).deleted_count)
            return total
        finally:
            client.close()

    def _delete_neo4j(self, role_id: str) -> int:
        query = """
        MATCH (n {role_id: $role_id})
        WITH collect(n) AS nodes
        FOREACH (n IN nodes | DETACH DELETE n)
        RETURN size(nodes) AS deleted
        """
        rows = self._neo4j.execute_write(query, {"role_id": role_id})
        result = self._run(rows) if hasattr(rows, "__await__") else rows
        return int(result[0].get("deleted", 0)) if result else 0

    def _delete_milvus(self, role_id: str) -> int:
        from pymilvus import MilvusClient
        uri = getattr(self, "_milvus_uri", "http://127.0.0.1:19530")
        database = getattr(self, "_milvus_db_name", "superCog")
        token_value = getattr(self, "_milvus_token", "")
        client = None
        try:
            kwargs = {
                "uri": uri,
                "db_name": database,
            }
            if token_value:
                kwargs["token"] = token_value
            client = MilvusClient(**kwargs)
            total = 0
            for collection in client.list_collections():
                result = client.delete(collection_name=collection, filter=f'role_id == "{role_id}"')
                if isinstance(result, dict):
                    total += int(result.get("delete_count", 0) or 0)
            return total
        except Exception as exc:
            raise MemProError("Milvus deletion failed") from exc
        finally:
            if client is not None:
                close = getattr(client, "close", None)
                if callable(close):
                    close()

