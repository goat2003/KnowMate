"""Request-scoped retrieval trace helpers.

Trace objects are deliberately plain dictionaries so they can be copied at
route boundaries and serialized in HTTP diagnostics without coupling the
retrievers to the service implementation.
"""

from __future__ import annotations

from typing import Any, Dict, MutableMapping, Optional

from app.retrieval.models import EvidenceItem, json_safe


TRACE_STAGES = ("raw_hits", "has_fact_bindings", "route_candidates", "merge", "selected")


def new_trace(*, sub_query_index: Optional[int] = None, route: Optional[str] = None, sub_query: str = "") -> Dict[str, Any]:
    return {
        "sub_query_index": sub_query_index,
        "route": route,
        "sub_query": sub_query,
        "stages": {stage: [] for stage in TRACE_STAGES},
        "errors": [],
    }


def record(trace: Optional[MutableMapping[str, Any]], stage: str, value: Any) -> None:
    if trace is None or stage not in TRACE_STAGES:
        return
    stages = trace.setdefault("stages", {})
    stages.setdefault(stage, []).append(json_safe(value))


def error(trace: Optional[MutableMapping[str, Any]], stage: str, exc: Any) -> None:
    if trace is None:
        return
    trace.setdefault("errors", []).append({"stage": stage, "error": str(exc)})


def evidence(item: EvidenceItem, *, identity: Optional[str] = None) -> Dict[str, Any]:
    result = {
        "chunk_uuid": item.chunk_uuid,
        "ori_fact_uuid": item.ori_fact_uuid,
        "fact_uuid": item.fact_uuid,
        "source": item.source,
        "valid_time": json_safe(item.valid_time),
        "local_score": item.local_score,
        "final_score": item.final_score,
        "route_raw_hit_ranks": json_safe(item.metadata.get("route_raw_hit_ranks") or {}),
        "route_retrieval_scores": json_safe(item.metadata.get("route_retrieval_scores") or {}),
    }
    if identity is not None:
        result["identity"] = identity
    return result


def row(value: Dict[str, Any], *, source: str = "") -> Dict[str, Any]:
    """Normalize a raw DB/vector row to the required evidence fields."""

    ori_fact_uuid = value.get("ori_fact_uuid") or value.get("fact_uuid") or value.get("uuid")
    fact_uuid = value.get("fact_uuid") or ori_fact_uuid
    return {
        "chunk_uuid": value.get("chunk_uuid"),
        "ori_fact_uuid": ori_fact_uuid,
        "fact_uuid": fact_uuid,
        "source": source or value.get("source") or value.get("kind") or "",
        "valid_time": json_safe(value.get("valid_time") or value.get("chunk_valid_time")),
        "local_score": value.get("local_score") or value.get("text_score") or value.get("vector_score") or value.get("edge_retrieval_score") or 0.0,
        "final_score": value.get("final_score") or 0.0,
    }
