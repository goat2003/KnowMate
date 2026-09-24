"""Small Milvus raw-search adapters for retrieval."""

from __future__ import annotations

from typing import Any, Iterable, List, Optional


def search_raw_hits(
    milvus_crud: Any,
    collection_name: str,
    embedding: Iterable[float],
    vector_field: str,
    top_k: int,
    expr: Optional[str] = None,
) -> Any:
    return milvus_crud.search_(
        collection_name=collection_name,
        embedding=list(embedding),
        vector_field=vector_field,
        top_k=top_k,
        expr=expr,
    )


def first_hit_page(raw_result: Any) -> List[Any]:
    if not raw_result:
        return []
    try:
        return list(raw_result[0] or [])
    except (TypeError, IndexError):
        return []


def quote_expr_value(value: Any) -> str:
    text = str(value or "")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
