from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "common"))

from simple_http_mcp import ToolError, ToolSpec, require_str, run_server  # noqa: E402


DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "8"))
CONFIG = {
    "mock_mode": os.getenv("EMBEDDING_MOCK_MODE", "true").lower() != "false",
    "real_embedding_endpoint": os.getenv("REAL_EMBEDDING_ENDPOINT", ""),
    "dimension": DIMENSION,
}

TOOLS = [
    ToolSpec(
        name="embed_text",
        description="Create a deterministic mock embedding for one text input.",
        input_schema={"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}},
        output_schema={
            "type": "object",
            "properties": {
                "embedding": {"type": "array", "items": {"type": "number"}},
                "dim": {"type": "integer"},
                "model": {"type": "string"},
                "mock": {"type": "boolean"},
            },
        },
        examples=[
            {
                "request": {"text": "agent workflow"},
                "response": {"embedding": [0.1961, 0.5333], "dim": DIMENSION, "model": "mock-hash-embedding-v1"},
            }
        ],
    ),
    ToolSpec(
        name="embed_batch",
        description="Create deterministic mock embeddings for multiple text inputs.",
        input_schema={"type": "object", "required": ["texts"], "properties": {"texts": {"type": "array"}}},
        output_schema={"type": "object", "properties": {"items": {"type": "array"}, "dim": {"type": "integer"}}},
        examples=[
            {
                "request": {"texts": ["agent workflow", "knowledge memory"]},
                "response": {"items": [{"index": 0, "embedding": [0.1961, 0.5333]}], "dim": DIMENSION},
            }
        ],
    ),
]


def handle(tool: str, payload: dict[str, object]) -> dict[str, object]:
    if tool == "embed_text":
        text = require_str(payload, "text")
        return _embed_one(text)
    if tool == "embed_batch":
        texts = payload.get("texts")
        if not isinstance(texts, list):
            raise ToolError("`texts` must be an array of strings", data={"field": "texts"})
        return {"items": [{"index": idx, **_embed_one(str(text))} for idx, text in enumerate(texts)], "dim": DIMENSION}
    raise ToolError(f"unknown tool `{tool}`", code=-32601)


def _embed_one(text: str) -> dict[str, object]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = []
    for idx in range(DIMENSION):
        byte = digest[idx % len(digest)]
        values.append(round((byte / 255.0) * 2 - 1, 6))
    return {
        "embedding": values,
        "dim": DIMENSION,
        "model": "mock-hash-embedding-v1",
        "mock": CONFIG["mock_mode"],
    }


if __name__ == "__main__":
    run_server("embedding-mcp", int(os.getenv("PORT", "7001")), TOOLS, handle, CONFIG)
