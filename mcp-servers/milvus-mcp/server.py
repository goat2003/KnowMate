from __future__ import annotations

import math
import os
from pathlib import Path
import sys
from uuid import uuid4

sys.path.append(str(Path(__file__).resolve().parents[1] / "common"))

from simple_http_mcp import (  # noqa: E402
    ToolError,
    ToolSpec,
    optional_number_list,
    require_object,
    require_str,
    run_server,
)


CONFIG = {
    "mock_mode": os.getenv("MILVUS_MOCK_MODE", "true").lower() != "false",
    "milvus_uri": os.getenv("MILVUS_URI", "http://127.0.0.1:19530"),
    "collection": os.getenv("MILVUS_COLLECTION", "knowledge_memory"),
}

MEMORY_STORE: dict[str, dict[str, object]] = {}

TOOLS = [
    ToolSpec(
        name="insert_memory_vector",
        description="Insert or update one memory vector in the in-memory mock vector store.",
        input_schema={"type": "object", "required": ["id", "embedding"], "properties": {"id": {"type": "string"}, "embedding": {"type": "array"}, "metadata": {"type": "object"}}},
        output_schema={"type": "object", "properties": {"upserted": {"type": "boolean"}, "id": {"type": "string"}}},
        examples=[{"request": {"id": "m1", "embedding": [0.1, 0.2], "metadata": {"topic": "AI"}}, "response": {"upserted": True, "id": "m1"}}],
    ),
    ToolSpec(
        name="search_similar_memory",
        description="Search the in-memory mock vector store for similar memory vectors.",
        input_schema={"type": "object", "required": ["embedding"], "properties": {"embedding": {"type": "array"}, "limit": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {"matches": {"type": "array"}}},
        examples=[{"request": {"embedding": [0.1, 0.2], "limit": 3}, "response": {"matches": [{"id": "m1", "score": 1.0}]}}],
    ),
    ToolSpec(
        name="search_related_articles",
        description="Return mock related articles for an embedding or topic.",
        input_schema={"type": "object", "properties": {"embedding": {"type": "array"}, "topic": {"type": "string"}, "limit": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {"matches": {"type": "array"}}},
        examples=[{"request": {"topic": "AI"}, "response": {"matches": [{"article_id": "mock-related-1", "score": 0.81}]}}],
    ),
    ToolSpec(
        name="search_articles",
        description="Return mock articles for a topic query. This is an alias reserved for Summary Agent retrieval.",
        input_schema={"type": "object", "properties": {"topic": {"type": "string"}, "limit": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {"matches": {"type": "array"}}},
        examples=[{"request": {"topic": "AI"}, "response": {"matches": [{"article_id": "mock-related-1", "score": 0.81}]}}],
    ),
    ToolSpec(
        name="semantic_deduplicate",
        description="Group semantically duplicate candidate articles by text similarity.",
        input_schema={"type": "object", "required": ["items"], "properties": {"items": {"type": "array"}, "threshold": {"type": "number"}}},
        output_schema={"type": "object", "properties": {"unique_items": {"type": "array"}, "duplicate_groups": {"type": "array"}}},
        examples=[{"request": {"items": [{"id": "a1", "text": "AI note"}]}, "response": {"unique_items": ["a1"], "duplicate_groups": []}}],
    ),
]


def handle(tool: str, payload: dict[str, object]) -> dict[str, object]:
    if tool == "insert_memory_vector":
        return _insert_memory_vector(payload)
    if tool == "search_similar_memory":
        embedding = optional_number_list(payload, "embedding")
        limit = _limit(payload)
        return {"matches": _search_store(embedding, limit), "mock": CONFIG["mock_mode"]}
    if tool in {"search_related_articles", "search_articles"}:
        embedding = optional_number_list(payload, "embedding", [0.31, 0.27, 0.93])
        limit = _limit(payload)
        matches = _search_store(embedding, limit)
        if not matches:
            topic = str(payload.get("topic", "general"))
            matches = [
                {"article_id": f"mock-related-{idx}", "title": f"{topic} related article {idx}", "score": round(0.92 - idx * 0.07, 4)}
                for idx in range(1, limit + 1)
            ]
        return {"matches": matches, "mock": CONFIG["mock_mode"]}
    if tool == "semantic_deduplicate":
        return _semantic_deduplicate(payload)
    raise ToolError(f"unknown tool `{tool}`", code=-32601)


def _insert_memory_vector(payload: dict[str, object]) -> dict[str, object]:
    memory_id = require_str(payload, "id")
    embedding = optional_number_list(payload, "embedding")
    metadata = require_object(payload, "metadata", {})
    if not embedding:
        raise ToolError("`embedding` cannot be empty", data={"field": "embedding"})
    MEMORY_STORE[memory_id] = {"id": memory_id, "embedding": embedding, "metadata": metadata}
    return {"upserted": True, "id": memory_id, "count": len(MEMORY_STORE), "mock": CONFIG["mock_mode"]}


def _search_store(embedding: list[float], limit: int) -> list[dict[str, object]]:
    if not MEMORY_STORE:
        _seed_store()
    scored = []
    for memory in MEMORY_STORE.values():
        score = _cosine(embedding, memory["embedding"])  # type: ignore[arg-type]
        scored.append({"id": memory["id"], "score": round(score, 6), "metadata": memory["metadata"]})
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


def _semantic_deduplicate(payload: dict[str, object]) -> dict[str, object]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise ToolError("`items` must be an array", data={"field": "items"})
    threshold = float(payload.get("threshold", 0.88) or 0.88)
    unique: list[str] = []
    duplicate_groups: list[dict[str, object]] = []
    fingerprints: dict[str, str] = {}
    for raw in items:
        if not isinstance(raw, dict):
            raise ToolError("each item must be an object", data={"field": "items"})
        item_id = str(raw.get("id") or uuid4().hex)
        text = str(raw.get("text") or raw.get("title") or "")
        fingerprint = " ".join(sorted(set(text.lower().split())))
        duplicate_of = next((existing for existing, fp in fingerprints.items() if _jaccard(fp, fingerprint) >= threshold), "")
        if duplicate_of:
            duplicate_groups.append({"canonical_id": duplicate_of, "duplicate_id": item_id, "score": _jaccard(fingerprints[duplicate_of], fingerprint)})
        else:
            unique.append(item_id)
            fingerprints[item_id] = fingerprint
    return {"unique_items": unique, "duplicate_groups": duplicate_groups, "threshold": threshold, "mock": CONFIG["mock_mode"]}


def _seed_store() -> None:
    MEMORY_STORE["seed-ai"] = {"id": "seed-ai", "embedding": [0.2, 0.4, 0.6], "metadata": {"topic": "AI"}}
    MEMORY_STORE["seed-kg"] = {"id": "seed-kg", "embedding": [0.1, 0.8, 0.3], "metadata": {"topic": "knowledge-graph"}}


def _cosine(a: list[float], b: list[float]) -> float:
    size = min(len(a), len(b))
    if size == 0:
        return 0.0
    dot = sum(a[idx] * b[idx] for idx in range(size))
    norm_a = math.sqrt(sum(value * value for value in a[:size]))
    norm_b = math.sqrt(sum(value * value for value in b[:size]))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def _jaccard(left: str, right: str) -> float:
    a = set(left.split())
    b = set(right.split())
    if not a and not b:
        return 1.0
    return len(a & b) / max(len(a | b), 1)


def _limit(payload: dict[str, object]) -> int:
    limit = int(payload.get("limit", 3) or 3)
    return max(1, min(limit, 20))


if __name__ == "__main__":
    run_server("milvus-mcp", int(os.getenv("PORT", "7003")), TOOLS, handle, CONFIG)
