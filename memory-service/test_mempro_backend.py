import unittest
from unittest.mock import AsyncMock

from mempro_backend import MemProBackend, MemProError


class _Result:
    def to_dict(self):
        return {
            "prompt_context": "用户偏好 Go",
            "evidence_items": [
                {"content": "用户明确学习 Go", "source": "fact", "final_score": 0.9, "fact_uuid": "secret-id"}
            ],
            "debug": {"cypher": "MATCH (n) RETURN n", "token": "secret"},
        }


class MemProBackendTest(unittest.TestCase):
    def test_health_does_not_report_false_connectivity_as_ready(self):
        backend = object.__new__(MemProBackend)
        for connected, expected in ((True, "ready"), (False, "unavailable")):
            backend._neo4j = type("Manager", (), {"verify_connectivity": AsyncMock(return_value=connected)})()
            self.assertEqual(backend._ping_neo4j(), expected)
        backend._neo4j.verify_connectivity.side_effect = RuntimeError("offline")
        self.assertEqual(backend._ping_neo4j(), "unavailable")

    def test_generated_identity_is_removed_from_all_public_text(self):
        role = "km_" + "a" * 40
        other_role = "km_" + "b" * 40
        backend = object.__new__(MemProBackend)
        backend.initialize = lambda: None
        result = _Result()
        result.to_dict = lambda: {
            "prompt_context": role + " likes Go",
            "evidence_items": [{"content": other_role + " likes databases", "source": role}],
        }
        backend._retriever = type("Retriever", (), {"retrieve": AsyncMock(return_value=result)})()
        backend._user_store = type("Store", (), {"get_user_profile": AsyncMock(return_value={
            "basic_info": "private address", "preference": role + " likes Go", "skill": "backend",
        })})()
        retrieved = backend.retrieve(role, "preferences")
        listed = backend.list(role)
        for payload in (retrieved, listed):
            self.assertNotIn(role, str(payload))
            self.assertNotIn(other_role, str(payload))
            self.assertNotIn("private address", str(payload))
        self.assertEqual(listed[0]["value"], "当前用户 likes Go")
        self.assertEqual(listed[0]["evidence"], "长期偏好画像")

    def test_retrieve_returns_only_bounded_context(self):
        backend = object.__new__(MemProBackend)
        backend._initialized = True
        backend._retriever = type("Retriever", (), {"retrieve": AsyncMock(return_value=_Result())})()
        backend._user_store = type("Store", (), {"get_user_profile": AsyncMock(return_value={"preference": "Go"})})()
        backend.initialize = lambda: None

        result = backend.retrieve("km_" + "a" * 40, "我喜欢 Go")
        self.assertEqual(result["memory"]["preference"], "Go")
        self.assertEqual(result["retrieval"]["items"][0]["content"], "用户明确学习 Go")
        self.assertNotIn("debug", result["retrieval"])
        self.assertNotIn("fact_uuid", str(result))
        self.assertNotIn("cypher", str(result))

    def test_invalid_role_is_rejected_before_backend_call(self):
        backend = object.__new__(MemProBackend)
        backend._initialized = True
        backend._retriever = None
        backend._user_store = None
        backend.initialize = lambda: None
        with self.assertRaises(MemProError):
            backend.retrieve("user-a", "hello")

    def test_list_maps_internal_profile_fields(self):
        backend = object.__new__(MemProBackend)
        backend._initialized = True
        backend._user_store = type("Store", (), {"get_user_profile": AsyncMock(return_value={
            "basic_info": "真实姓名和地址",
            "preference": "Go",
            "skill": "后端开发",
        })})()
        backend.initialize = lambda: None

        items = backend.list("km_" + "b" * 40)
        self.assertEqual([item["key"] for item in items], ["interests", "level"])
        self.assertNotIn("basic_info", str(items))
        self.assertNotIn("真实姓名", str(items))

    def test_delete_milvus_uses_mempro_database_and_all_collections(self):
        backend = object.__new__(MemProBackend)
        class FakeClient:
            instances = []
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.deleted = []
                FakeClient.instances.append(self)
            def list_collections(self):
                return ["chunk_schema", "ori_fact_schema", "dev_fact_schema", "SemanticEntity"]
            def delete(self, collection_name, filter):
                self.deleted.append((collection_name, filter))
                return {"delete_count": 2}
            def close(self):
                self.closed = True
        import sys
        import types
        fake = types.SimpleNamespace(MilvusClient=FakeClient)
        old = sys.modules.get("pymilvus")
        sys.modules["pymilvus"] = fake
        old_db = __import__("os").environ.pop("MILVUS_DB_NAME", None)
        try:
            self.assertEqual(backend._delete_milvus("km_" + "c" * 40), 8)
            client = FakeClient.instances[-1]
            self.assertEqual(client.kwargs["db_name"], "superCog")
            self.assertEqual([name for name, _ in client.deleted], ["chunk_schema", "ori_fact_schema", "dev_fact_schema", "SemanticEntity"])
            self.assertTrue(all('role_id == "km_' in expr for _, expr in client.deleted))
            self.assertTrue(client.closed)
        finally:
            if old is None:
                sys.modules.pop("pymilvus", None)
            else:
                sys.modules["pymilvus"] = old
            if old_db is not None:
                __import__("os").environ["MILVUS_DB_NAME"] = old_db

    def test_delete_milvus_errors_are_not_suppressed(self):
        backend = object.__new__(MemProBackend)
        import sys
        import types
        class BrokenClient:
            def __init__(self, **kwargs): pass
            def list_collections(self): raise RuntimeError("backend failure")
            def close(self): pass
        old = sys.modules.get("pymilvus")
        sys.modules["pymilvus"] = types.SimpleNamespace(MilvusClient=BrokenClient)
        try:
            with self.assertRaises(MemProError):
                backend._delete_milvus("km_" + "d" * 40)
        finally:
            if old is None:
                sys.modules.pop("pymilvus", None)
            else:
                sys.modules["pymilvus"] = old


if __name__ == "__main__":
    unittest.main()
