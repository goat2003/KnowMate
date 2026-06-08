from __future__ import annotations

import os
from pathlib import Path
import sys


SERVER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(SERVER_DIR.parent / "common"))

from embedding_provider import EmbeddingProviderError, MemoryEmbeddingProvider, OpenAIEmbeddingProvider  # noqa: E402
from provider import ManagedProvider, ProviderUnavailableError, read_secret  # noqa: E402
from simple_http_mcp import ToolError, ToolSpec, require_str, run_server  # noqa: E402


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


def _provider_mode() -> str:
    explicit = os.getenv("EMBEDDING_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    return "memory" if _bool_env("EMBEDDING_MOCK_MODE", True) else "openai"


def _optional_float(name: str) -> float | None:
    value = os.getenv(name, "").strip()
    return float(value) if value else None


MODE = _provider_mode()
DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "8" if MODE == "memory" else "3072"))
CONFIG = {
    "mode": MODE,
    "model": os.getenv("EMBEDDING_MODEL", "text-embedding-3-large"),
    "dimension": DIMENSION,
    "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
}


def _build_provider():
    if MODE == "memory":
        return MemoryEmbeddingProvider(dimension=DIMENSION)
    if MODE != "openai":
        raise EmbeddingProviderError(f"unsupported EMBEDDING_PROVIDER `{MODE}`")
    return OpenAIEmbeddingProvider(
        api_key=read_secret("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY_FILE", "")),
        base_url=str(CONFIG["base_url"]),
        model=str(CONFIG["model"]),
        dimension=DIMENSION,
        timeout_seconds=float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "30")),
        max_retries=int(os.getenv("EMBEDDING_MAX_RETRIES", "2")),
        retry_backoff_seconds=float(os.getenv("EMBEDDING_RETRY_BACKOFF_SECONDS", "0.1")),
        batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "64")),
        max_chars_per_chunk=int(os.getenv("EMBEDDING_MAX_CHARS_PER_CHUNK", "12000")),
        max_chunks=int(os.getenv("EMBEDDING_MAX_CHUNKS", "8")),
        cache_size=int(os.getenv("EMBEDDING_CACHE_SIZE", "1024")),
        cache_ttl_seconds=float(os.getenv("EMBEDDING_CACHE_TTL_SECONDS", "3600")),
        cost_per_million_tokens_usd=_optional_float("EMBEDDING_COST_PER_MILLION_TOKENS_USD"),
    )


MANAGED = ManagedProvider(_build_provider, mode=MODE)

EMBEDDING_RESULT_SCHEMA = {
    "type": "object",
    "required": ["embedding", "dim", "model", "provider", "mock"],
    "properties": {
        "embedding": {"type": "array", "items": {"type": "number"}},
        "dim": {"type": "integer"},
        "model": {"type": "string"},
        "provider": {"type": "string"},
        "mock": {"type": "boolean"},
        "cache_hit": {"type": "boolean"},
        "token_count": {"type": "integer"},
        "latency_ms": {"type": "integer"},
        "estimated_cost_usd": {"type": ["number", "null"]},
        "truncated": {"type": "boolean"},
        "chunk_count": {"type": "integer"},
    },
}

TOOLS = [
    ToolSpec(
        name="embed_text",
        description="Create one embedding using the configured memory or OpenAI-compatible provider.",
        input_schema={
            "type": "object",
            "required": ["text"],
            "properties": {"text": {"type": "string"}, "metadata": {"type": "object"}},
            "additionalProperties": False,
        },
        output_schema=EMBEDDING_RESULT_SCHEMA,
        examples=[{"request": {"text": "agent workflow"}, "response": {"embedding": [0.1], "dim": DIMENSION}}],
    ),
    ToolSpec(
        name="embed_batch",
        description="Create embeddings for multiple texts using bounded provider batches.",
        input_schema={
            "type": "object",
            "required": ["texts"],
            "properties": {
                "texts": {"type": "array", "items": {"type": "string"}, "maxItems": 1024},
                "metadata": {"type": "object"},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["items", "embeddings", "dim", "model", "provider", "mock"],
            "properties": {
                "items": {"type": "array"},
                "embeddings": {"type": "array"},
                "dim": {"type": "integer"},
                "model": {"type": "string"},
                "provider": {"type": "string"},
                "mock": {"type": "boolean"},
                "token_count": {"type": "integer"},
                "estimated_cost_usd": {"type": ["number", "null"]},
            },
        },
        examples=[{"request": {"texts": ["agent workflow"]}, "response": {"items": [], "dim": DIMENSION}}],
    ),
]


def handle(tool: str, payload: dict[str, object]) -> dict[str, object]:
    try:
        provider = MANAGED.get()
        if tool == "embed_text":
            return provider.embed_text(require_str(payload, "text"), payload.get("metadata"))  # type: ignore[attr-defined,arg-type]
        if tool == "embed_batch":
            texts = payload.get("texts")
            if not isinstance(texts, list) or not all(isinstance(text, str) for text in texts):
                raise ToolError("`texts` must be an array of strings", data={"field": "texts"})
            return provider.embed_batch(texts, payload.get("metadata"))  # type: ignore[attr-defined,arg-type]
        raise ToolError(f"unknown tool `{tool}`", code=-32601)
    except ToolError:
        raise
    except (ProviderUnavailableError, EmbeddingProviderError) as exc:
        raise ToolError(str(exc), data={"provider": MODE}) from exc


if __name__ == "__main__":
    run_server(
        "embedding-mcp",
        int(os.getenv("PORT", "7001")),
        TOOLS,
        handle,
        CONFIG,
        health_provider=MANAGED.health,
        lifecycle=MANAGED,
    )
