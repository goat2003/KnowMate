from __future__ import annotations

from pathlib import Path
import sys
import unittest


SERVER_DIR = Path(__file__).resolve().parents[1] / "milvus-mcp"
sys.path.insert(0, str(SERVER_DIR))

from milvus_store import (  # noqa: E402
    MemoryVectorStore,
    MilvusVectorStore,
    VectorStoreError,
    compile_metadata_filter,
    stable_memory_id,
)


class FakeSchema:
    def __init__(self) -> None:
        self.fields: list[dict[str, object]] = []

    def add_field(self, **kwargs: object) -> None:
        self.fields.append(kwargs)


class FakeIndexes:
    def __init__(self) -> None:
        self.indexes: list[dict[str, object]] = []

    def add_index(self, **kwargs: object) -> None:
        self.indexes.append(kwargs)


class FakeMilvusClient:
    def __init__(self, *, exists: bool, description: dict[str, object] | None = None) -> None:
        self.exists = exists
        self.description = description or {}
        self.created: list[dict[str, object]] = []
        self.loaded: list[str] = []
        self.closed = False
        self.drop_calls = 0

    def has_collection(self, collection_name: str, timeout: float | None = None) -> bool:
        return self.exists

    def create_schema(self, **kwargs: object) -> FakeSchema:
        return FakeSchema()

    def prepare_index_params(self) -> FakeIndexes:
        return FakeIndexes()

    def create_collection(self, **kwargs: object) -> None:
        self.created.append(kwargs)

    def describe_collection(self, collection_name: str, timeout: float | None = None) -> dict[str, object]:
        return self.description

    def load_collection(self, collection_name: str, timeout: float | None = None) -> None:
        self.loaded.append(collection_name)

    def list_collections(self, timeout: float | None = None) -> list[str]:
        return ["user_memory_vectors"]

    def close(self) -> None:
        self.closed = True

    def drop_collection(self, collection_name: str) -> None:
        self.drop_calls += 1


class MilvusStoreTest(unittest.TestCase):
    def test_stable_id_is_repeatable_and_changes_with_user(self) -> None:
        first = stable_memory_id("u1", "feedback", "external-1", "")
        second = stable_memory_id("u1", "feedback", "external-1", "")
        other = stable_memory_id("u2", "feedback", "external-1", "")

        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertEqual(len(first), 64)

    def test_memory_store_supports_upsert_search_filter_and_delete(self) -> None:
        store = MemoryVectorStore(dimension=3)
        store.initialize()
        first = store.upsert(
            {"embedding": [1, 0, 0], "user_id": "u1", "source": "feedback", "external_id": "e1", "topic": "AI"}
        )
        store.upsert(
            {"embedding": [0, 1, 0], "user_id": "u2", "source": "feedback", "external_id": "e2", "topic": "DB"}
        )

        matches = store.search([1, 0, 0], limit=5, metadata_filter={"user_id": {"eq": "u1"}})
        deleted = store.delete(ids=[first["id"]])

        self.assertEqual([match["id"] for match in matches], [first["id"]])
        self.assertEqual(deleted["deleted_count"], 1)
        self.assertEqual(store.search([1, 0, 0], limit=5, metadata_filter={"user_id": {"eq": "u1"}}), [])

    def test_dimension_mismatch_is_rejected(self) -> None:
        store = MemoryVectorStore(dimension=3)

        with self.assertRaisesRegex(VectorStoreError, "dimension"):
            store.upsert({"embedding": [1, 0], "user_id": "u1", "source": "feedback"})

    def test_empty_delete_is_rejected(self) -> None:
        store = MemoryVectorStore(dimension=3)

        with self.assertRaisesRegex(VectorStoreError, "unqualified delete"):
            store.delete()

    def test_vector_deduplication_finds_batch_and_existing_duplicates(self) -> None:
        store = MemoryVectorStore(dimension=3)
        store.upsert({"id": "existing", "embedding": [1, 0, 0], "user_id": "u1", "source": "feedback"})

        result = store.deduplicate(
            [
                {"id": "new-1", "embedding": [1, 0, 0], "user_id": "u1", "source": "feedback"},
                {"id": "new-2", "embedding": [0, 1, 0], "user_id": "u1", "source": "feedback"},
                {"id": "new-3", "embedding": [0, 1, 0], "user_id": "u1", "source": "feedback"},
            ],
            threshold=0.99,
            metadata_filter={"user_id": {"eq": "u1"}},
        )

        self.assertEqual(result["unique_items"], ["new-2"])
        self.assertEqual(len(result["duplicate_groups"]), 2)

    def test_filter_compiler_accepts_only_structured_allowlisted_filters(self) -> None:
        expression = compile_metadata_filter(
            {
                "user_id": {"eq": "u'1"},
                "topic": {"in": ["AI", "ML"]},
                "created_at": {"gte": 10},
            }
        )

        self.assertIn("user_id = 'u\\'1'", expression)
        self.assertIn("topic in ['AI', 'ML']", expression)
        self.assertIn("created_at >= 10", expression)
        with self.assertRaisesRegex(VectorStoreError, "not allowed"):
            compile_metadata_filter({"embedding": {"eq": "unsafe"}})

    def test_real_store_creates_collection_and_hnsw_index(self) -> None:
        client = FakeMilvusClient(exists=False)
        store = MilvusVectorStore(client=client, dimension=3)

        store.initialize()

        self.assertEqual(len(client.created), 1)
        indexes = client.created[0]["index_params"]
        self.assertEqual(indexes.indexes[0]["index_type"], "HNSW")
        self.assertEqual(client.loaded, ["user_memory_vectors"])

    def test_real_store_rejects_incompatible_dimension_without_drop(self) -> None:
        client = FakeMilvusClient(
            exists=True,
            description={
                "fields": [
                    {"name": "id", "type": "VARCHAR", "is_primary": True},
                    {"name": "embedding", "type": "FLOAT_VECTOR", "params": {"dim": 8}},
                ]
            },
        )
        store = MilvusVectorStore(client=client, dimension=3)

        with self.assertRaisesRegex(VectorStoreError, "dimension"):
            store.initialize()

        self.assertEqual(client.drop_calls, 0)

    def test_real_store_rejects_incompatible_field_type_without_drop(self) -> None:
        fields = [
            {"name": "id", "type": "INT64", "is_primary": True},
            {"name": "embedding", "type": "FLOAT_VECTOR", "params": {"dim": 3}},
        ]
        fields.extend(
            {"name": name, "type": "VARCHAR"}
            for name in ["user_id", "source", "topic", "external_id", "content_hash"]
        )
        fields.extend(
            [
                {"name": "created_at", "type": "INT64"},
                {"name": "metadata_json", "type": "JSON"},
            ]
        )
        client = FakeMilvusClient(exists=True, description={"fields": fields})
        store = MilvusVectorStore(client=client, dimension=3)

        with self.assertRaisesRegex(VectorStoreError, "field `id` type"):
            store.initialize()

        self.assertEqual(client.drop_calls, 0)


if __name__ == "__main__":
    unittest.main()
