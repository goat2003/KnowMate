"""Shared retrieval data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional


def clamp_score(value: Any) -> float:
    """Clamp arbitrary numeric input into the 0-1 score range."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number < 0:
        return 0.0
    if number > 1:
        return 1.0
    return number


def json_safe(value: Any) -> Any:
    """Convert Neo4j/Python values into JSON-serializable primitives."""

    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "to_native"):
        return json_safe(value.to_native())
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return str(value)


@dataclass
class EvidenceItem:
    source: str
    content: str
    local_score: float
    evidence_type: str
    ori_fact_uuid: Optional[str] = None
    dev_uuid: Optional[str] = None
    chunk_uuid: Optional[str] = None
    fact_uuid: Optional[str] = None
    chunk_content_index: Optional[int] = None
    entity_uuid: Optional[str] = None
    path: Optional[List[Dict[str, Any]]] = None
    valid_time: Optional[Any] = None
    create_time: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    sources: List[str] = field(default_factory=list)
    final_score: float = 0.0

    def __post_init__(self) -> None:
        self.source = str(self.source or "").strip()
        self.content = str(self.content or "").strip()
        self.evidence_type = str(self.evidence_type or "").strip()
        self.local_score = clamp_score(self.local_score)
        self.final_score = clamp_score(self.final_score)
        if not self.sources and self.source:
            self.sources = [self.source]
        else:
            self.sources = sorted({str(source) for source in self.sources if source})
        if self.chunk_content_index is not None:
            try:
                self.chunk_content_index = int(self.chunk_content_index)
            except (TypeError, ValueError):
                self.chunk_content_index = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "content": self.content,
            "local_score": clamp_score(self.local_score),
            "evidence_type": self.evidence_type,
            "ori_fact_uuid": self.ori_fact_uuid,
            "dev_uuid": self.dev_uuid,
            "chunk_uuid": self.chunk_uuid,
            "fact_uuid": self.fact_uuid,
            "chunk_content_index": self.chunk_content_index,
            "entity_uuid": self.entity_uuid,
            "path": json_safe(self.path),
            "valid_time": json_safe(self.valid_time),
            "create_time": json_safe(self.create_time),
            "metadata": json_safe(self.metadata),
            "sources": list(self.sources),
            "final_score": clamp_score(self.final_score),
        }


@dataclass
class RetrievalResult:
    query: str
    sub_queries: List[Dict[str, Any]]
    evidence_items: List[EvidenceItem]
    prompt_context: str
    debug: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "sub_queries": json_safe(self.sub_queries),
            "evidence_items": [item.to_dict() for item in self.evidence_items],
            "prompt_context": self.prompt_context,
            "debug": json_safe(self.debug),
        }

