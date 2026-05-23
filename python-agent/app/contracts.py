from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


JsonDict = dict[str, Any]


def ensure_run_id(value: str | None) -> str:
    if value:
        return value
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"run-{stamp}-{uuid4().hex[:8]}"


def default_mcp_policy(policy: JsonDict | None = None) -> JsonDict:
    current = policy or {}
    has_explicit_enable = any(
        bool(current.get(key))
        for key in ["enable_embedding", "enable_fetch", "enable_milvus", "enable_neo4j"]
    )
    defaults = {
        "mock_transport": True,
        "enable_embedding": True,
        "enable_fetch": False,
        "enable_milvus": True,
        "enable_neo4j": True,
    }
    merged = defaults | current
    if has_explicit_enable:
        return merged
    return merged


def normalize_article(article: JsonDict) -> JsonDict:
    article_id = (
        article.get("article_id")
        or article.get("id")
        or article.get("url")
        or article.get("title")
        or f"article-{uuid4().hex[:8]}"
    )
    return {
        "article_id": str(article_id),
        "url": str(article.get("url", "")),
        "title": str(article.get("title", "")),
        "raw_text": str(article.get("raw_text") or article.get("content") or ""),
        "source": str(article.get("source", "")),
        "published_at": str(article.get("published_at", "")),
        "tags": list(article.get("tags", [])),
    }
