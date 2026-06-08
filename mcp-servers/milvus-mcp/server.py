from __future__ import annotations

import os
from pathlib import Path
import sys


SERVER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(SERVER_DIR.parent / "common"))

from milvus_store import MemoryVectorStore, MilvusVectorStore, VectorStoreError  # noqa: E402
from provider import ManagedProvider, ProviderUnavailableError, read_secret  # noqa: E402
from simple_http_mcp import ToolError, ToolSpec, optional_number_list, require_object, run_server  # noqa: E402


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


def _mode() -> str:
    explicit = os.getenv("MILVUS_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    return "memory" if _bool_env("MILVUS_MOCK_MODE", True) else "milvus"


MODE = _mode()
DIMENSION = int(os.getenv("MILVUS_DIMENSION", os.getenv("EMBEDDING_DIMENSION", "8" if MODE == "memory" else "3072")))
COLLECTION = os.getenv("MILVUS_COLLECTION", "user_memory_vectors")
CONFIG = {
    "mode": MODE,
    "milvus_uri": os.getenv("MILVUS_URI", "http://127.0.0.1:19530"),
    "collection": COLLECTION,
    "dimension": DIMENSION,
}


def _build_store():
    if MODE == "memory":
        return MemoryVectorStore(dimension=DIMENSION, collection_name=COLLECTION)
    if MODE != "milvus":
        raise VectorStoreError(f"unsupported MILVUS_PROVIDER `{MODE}`")
    return MilvusVectorStore(
        uri=str(CONFIG["milvus_uri"]),
        token=read_secret("MILVUS_TOKEN", os.getenv("MILVUS_TOKEN_FILE", "")),
        collection_name=COLLECTION,
        dimension=DIMENSION,
        timeout_seconds=float(os.getenv("MILVUS_TIMEOUT_SECONDS", "10")),
    )


MANAGED = ManagedProvider(_build_store, mode=MODE)

FILTER_SCHEMA = {
    "type": "object",
    "additionalProperties": {
        "type": "object",
        "minProperties": 1,
        "maxProperties": 1,
        "properties": {
            "eq": {},
            "in": {"type": "array"},
            "gte": {},
            "lte": {},
        },
        "additionalProperties": False,
    },
}

ITEM_SCHEMA = {
    "type": "object",
    "required": ["embedding"],
    "properties": {
        "id": {"type": "string"},
        "embedding": {"type": "array", "items": {"type": "number"}},
        "user_id": {"type": "string"},
        "source": {"type": "string"},
        "topic": {"type": "string"},
        "external_id": {"type": "string"},
        "content": {},
        "content_hash": {"type": "string"},
        "created_at": {"type": "integer"},
        "metadata": {"type": "object"},
    },
    "additionalProperties": False,
}

TOOLS = [
    ToolSpec(
        name="insert_memory_vector",
        description="Idempotently upsert one memory vector using an explicit or stable generated ID.",
        input_schema=ITEM_SCHEMA,
        output_schema={
            "type": "object",
            "required": ["upserted", "id"],
            "properties": {"upserted": {"type": "boolean"}, "id": {"type": "string"}, "mock": {"type": "boolean"}},
        },
        examples=[{"request": {"embedding": [0.1], "user_id": "u1", "source": "feedback"}, "response": {"upserted": True}}],
    ),
    ToolSpec(
        name="batch_insert_memory_vectors",
        description="Validate and idempotently upsert a batch of memory vectors.",
        input_schema={
            "type": "object",
            "required": ["items"],
            "properties": {"items": {"type": "array", "items": ITEM_SCHEMA, "maxItems": 1000}},
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["upserted_count", "ids"],
            "properties": {"upserted_count": {"type": "integer"}, "ids": {"type": "array"}, "mock": {"type": "boolean"}},
        },
        examples=[{"request": {"items": [{"embedding": [0.1]}]}, "response": {"upserted_count": 1}}],
    ),
    ToolSpec(
        name="search_similar_memory",
        description="Search memory vectors with an optional structured metadata filter.",
        input_schema={
            "type": "object",
            "required": ["embedding"],
            "properties": {
                "embedding": {"type": "array", "items": {"type": "number"}},
                "limit": {"type": "integer"},
                "minimum_score": {"type": "number"},
                "metadata_filter": FILTER_SCHEMA,
            },
            "additionalProperties": False,
        },
        output_schema={"type": "object", "required": ["matches"], "properties": {"matches": {"type": "array"}, "mock": {"type": "boolean"}}},
        examples=[{"request": {"embedding": [0.1]}, "response": {"matches": []}}],
    ),
    ToolSpec(
        name="search_related_articles",
        description="Compatibility alias for vector search over memory records.",
        input_schema={
            "type": "object",
            "properties": {
                "embedding": {"type": "array", "items": {"type": "number"}},
                "topic": {"type": "string"},
                "limit": {"type": "integer"},
                "metadata_filter": FILTER_SCHEMA,
            },
            "additionalProperties": False,
        },
        output_schema={"type": "object", "required": ["matches"], "properties": {"matches": {"type": "array"}, "mock": {"type": "boolean"}}},
        examples=[{"request": {"embedding": [0.1]}, "response": {"matches": []}}],
    ),
    ToolSpec(
        name="search_articles",
        description="Compatibility article-search alias; vector input is required for semantic results.",
        input_schema={
            "type": "object",
            "properties": {
                "embedding": {"type": "array", "items": {"type": "number"}},
                "topic": {"type": "string"},
                "limit": {"type": "integer"},
                "metadata_filter": FILTER_SCHEMA,
            },
            "additionalProperties": False,
        },
        output_schema={"type": "object", "required": ["matches"], "properties": {"matches": {"type": "array"}, "mock": {"type": "boolean"}}},
        examples=[{"request": {"topic": "AI"}, "response": {"matches": []}}],
    ),
    ToolSpec(
        name="delete_memory_vectors",
        description="Delete memory vectors by stable IDs or a non-empty structured metadata filter.",
        input_schema={
            "type": "object",
            "properties": {
                "ids": {"type": "array", "items": {"type": "string"}},
                "metadata_filter": FILTER_SCHEMA,
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["deleted_count"],
            "properties": {"deleted_count": {"type": "integer"}, "ids": {"type": "array"}, "mock": {"type": "boolean"}},
        },
        examples=[{"request": {"ids": ["id"]}, "response": {"deleted_count": 1}}],
    ),
    ToolSpec(
        name="semantic_deduplicate",
        description="Find semantic duplicates using incoming and stored vectors.",
        input_schema={
            "type": "object",
            "required": ["items"],
            "properties": {
                "items": {"type": "array", "items": ITEM_SCHEMA},
                "threshold": {"type": "number"},
                "metadata_filter": FILTER_SCHEMA,
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["unique_items", "duplicate_groups"],
            "properties": {"unique_items": {"type": "array"}, "duplicate_groups": {"type": "array"}, "mock": {"type": "boolean"}},
        },
        examples=[{"request": {"items": [{"embedding": [0.1]}]}, "response": {"unique_items": [], "duplicate_groups": []}}],
    ),
]


def _limit(payload: dict[str, object]) -> int:
    return max(1, min(int(payload.get("limit", 3) or 3), 100))


def _filter(payload: dict[str, object]) -> dict[str, object] | None:
    value = payload.get("metadata_filter")
    if value is None:
        return None
    return require_object(payload, "metadata_filter")


def _items(payload: dict[str, object]) -> list[dict[str, object]]:
    items = payload.get("items")
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ToolError("`items` must be an array of objects", data={"field": "items"})
    return items


def handle(tool: str, payload: dict[str, object]) -> dict[str, object]:
    try:
        store = MANAGED.get()
        if tool == "insert_memory_vector":
            return store.upsert(payload)  # type: ignore[attr-defined]
        if tool == "batch_insert_memory_vectors":
            return store.upsert_batch(_items(payload))  # type: ignore[attr-defined]
        if tool == "delete_memory_vectors":
            ids = payload.get("ids")
            if ids is not None and (not isinstance(ids, list) or not all(isinstance(item, str) for item in ids)):
                raise ToolError("`ids` must be an array of strings", data={"field": "ids"})
            return store.delete(ids=ids, metadata_filter=_filter(payload))  # type: ignore[attr-defined,arg-type]
        if tool == "semantic_deduplicate":
            return store.deduplicate(  # type: ignore[attr-defined]
                _items(payload),
                threshold=float(payload.get("threshold", 0.88) or 0.88),
                metadata_filter=_filter(payload),
            )
        if tool in {"search_similar_memory", "search_related_articles", "search_articles"}:
            embedding = optional_number_list(payload, "embedding")
            if not embedding:
                return {"matches": [], "mock": MODE == "memory"}
            matches = store.search(  # type: ignore[attr-defined]
                embedding,
                limit=_limit(payload),
                metadata_filter=_filter(payload),
                minimum_score=float(payload["minimum_score"]) if "minimum_score" in payload else None,
            )
            return {"matches": matches, "mock": MODE == "memory"}
        raise ToolError(f"unknown tool `{tool}`", code=-32601)
    except ToolError:
        raise
    except (ProviderUnavailableError, VectorStoreError) as exc:
        raise ToolError(str(exc), data={"provider": MODE, "collection": COLLECTION}) from exc


if __name__ == "__main__":
    run_server(
        "milvus-mcp",
        int(os.getenv("PORT", "7003")),
        TOOLS,
        handle,
        CONFIG,
        health_provider=MANAGED.health,
        lifecycle=MANAGED,
    )
