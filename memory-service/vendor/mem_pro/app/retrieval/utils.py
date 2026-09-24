"""Small utilities shared by retrieval modules."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Set


_LUCENE_SPECIAL_CHARS = set('+-&|!(){}[]^"~*?:\\/')
_KNOWN_FULLTEXT_INDEXES: Set[str] = set()
_MISSING_FULLTEXT_INDEXES: Set[str] = set()


def node_to_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    try:
        return dict(value)
    except Exception:
        pass
    if hasattr(value, "items"):
        try:
            return {key: item for key, item in value.items()}
        except Exception:
            return {}
    return {}


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def clean_text_list(values: Iterable[Any]) -> List[str]:
    result: List[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def escape_lucene_fulltext_query(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or not re.search(r"[\w\u4e00-\u9fff]", text):
        return ""
    return "".join(f"\\{char}" if char in _LUCENE_SPECIAL_CHARS else char for char in text)


async def fulltext_index_exists(manager: Any, index_name: str) -> bool:
    if index_name in _KNOWN_FULLTEXT_INDEXES:
        return True
    if index_name in _MISSING_FULLTEXT_INDEXES:
        return False

    rows = await manager.execute_query(
        """
        SHOW INDEXES
        YIELD name, type
        WHERE name = $index_name AND type = 'FULLTEXT'
        RETURN count(*) AS count
        """,
        {"index_name": index_name},
    )
    exists = bool(rows and int(rows[0].get("count") or 0) > 0)
    if exists:
        _KNOWN_FULLTEXT_INDEXES.add(index_name)
    else:
        _MISSING_FULLTEXT_INDEXES.add(index_name)
    return exists


def hit_entity(hit: Any) -> Dict[str, Any]:
    try:
        data = hit.entity.to_dict()
    except Exception:
        return {}
    if isinstance(data, dict) and isinstance(data.get("entity"), dict):
        return data["entity"]
    return data if isinstance(data, dict) else {}
