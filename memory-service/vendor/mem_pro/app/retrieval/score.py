"""Scoring helpers for retrieval evidence."""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional

from app.retrieval.models import EvidenceItem, clamp_score


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")

FACT_SCORE_WEIGHTS = {
    "retrieval_score": 0.55,
    "entity_match_score": 0.20,
    "fact_quality_score": 0.15,
    "time_score": 0.10,
}
SEMANTIC_EDGE_SCORE_WEIGHTS = {
    "start_entity_score": 0.18,
    "end_entity_score": 0.12,
    "edge_retrieval_score": 0.32,
    "fact_relevance_score": 0.22,
    "edge_quality_score": 0.11,
    "time_score": 0.05,
}
SEMANTIC_PATH_SCORE_WEIGHTS = {
    "start_entity_score": 0.18,
    "path_relevance_score": 0.30,
    "hop_score": 0.13,
    "edge_quality_score": 0.17,
    "source_score": 0.10,
    "time_score": 0.12,
}
FINAL_SCORE_WEIGHTS = {
    "local_score": 0.58,
    "route_match_score": 0.16,
    "evidence_quality_score": 0.12,
    "multi_source_support_score": 0.06,
    "time_score": 0.08,
}
VECTOR_SCORE_FORMULA = (
    "vector_score = rerank_score*0.80 + milvus_score*0.20 when rerank_score >= milvus_score; "
    "otherwise rerank_score*0.45 + milvus_score*0.55"
)


def score_formula(name: str, weights: Dict[str, float]) -> str:
    return f"{name} = " + " + ".join(f"{component}*{weight:.2f}" for component, weight in weights.items())


def tokenize(text: str) -> List[str]:
    return [token.lower() for token in _TOKEN_RE.findall(str(text or ""))]


def lexical_overlap_score(query: str, text: str) -> float:
    query_tokens = set(tokenize(query))
    text_tokens = set(tokenize(text))
    if not query_tokens or not text_tokens:
        return 0.0
    overlap = len(query_tokens & text_tokens) / len(query_tokens)
    sequence = SequenceMatcher(None, str(query or ""), str(text or "")).ratio()
    return clamp_score(overlap * 0.75 + sequence * 0.25)


def l2_distance_to_score(distance: Any) -> float:
    try:
        value = float(distance)
    except (TypeError, ValueError):
        return 0.0
    return clamp_score(1.0 / (1.0 + max(value, 0.0)))


def cosine_to_score(score: Any) -> float:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return 0.0
    if value < -1:
        return 0.0
    if value <= 1:
        return clamp_score((value + 1.0) / 2.0 if value < 0 else value)
    return 1.0


def normalize_scores(rows: List[Dict[str, Any]], score_key: str = "score") -> List[Dict[str, Any]]:
    if not rows:
        return rows
    raw_scores = []
    for row in rows:
        try:
            raw_scores.append(float(row.get(score_key, 0.0) or 0.0))
        except (TypeError, ValueError):
            raw_scores.append(0.0)
    max_score = max(raw_scores) if raw_scores else 0.0
    if max_score <= 0:
        for row in rows:
            row[score_key] = 0.5
        return rows
    for row, raw in zip(rows, raw_scores):
        row[score_key] = clamp_score(raw / max_score)
    return rows


def parse_time_value(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, list):
        for item in value:
            parsed = parse_time_value(item)
            if parsed is not None:
                return parsed
        return None
    if hasattr(value, "to_native"):
        return parse_time_value(value.to_native())
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_time_range(time_constraint: Optional[Dict[str, Any]]) -> tuple[Optional[datetime], Optional[datetime]]:
    if not time_constraint or not time_constraint.get("has_time_constraint"):
        return None, None
    start = parse_time_value(time_constraint.get("start"))
    end = parse_time_value(time_constraint.get("end"))
    raw = str(time_constraint.get("raw") or "")
    if start is None and end is None and raw:
        parsed = parse_time_value(raw)
        start = parsed
        end = parsed
    if start and end and start > end:
        start, end = end, start
    return start, end


def compute_time_score(
    time_constraint: Optional[Dict[str, Any]],
    candidate_time: Any,
    fallback_time: Any = None,
) -> float:
    """Score only dialogue event time stored on ChunkNode.valid_time.

    ``fallback_time`` remains in the signature for call-site compatibility, but
    build/storage timestamps must never influence event-time matching.
    """
    start, end = _parse_time_range(time_constraint)
    if start is None and end is None:
        return 0.5

    values = candidate_time if isinstance(candidate_time, list) else [candidate_time]

    parsed_values = [parse_time_value(value) for value in values]
    parsed_values = [value for value in parsed_values if value is not None]
    if not parsed_values:
        return 0.5

    for value in parsed_values:
        if start and end and start <= value <= end:
            return 1.0
        if start and not end and value >= start:
            return 1.0
        if end and not start and value <= end:
            return 1.0

    margin = timedelta(days=7)
    for value in parsed_values:
        lower = start - margin if start else None
        upper = end + margin if end else None
        if lower and upper and lower <= value <= upper:
            return 0.6
        if lower and not upper and value >= lower:
            return 0.6
        if upper and not lower and value <= upper:
            return 0.6
    return 0.0


def compute_entity_match_score(entities: Iterable[str], text: str) -> float:
    clean_entities = [str(entity).strip().lower() for entity in entities or [] if str(entity).strip()]
    if not clean_entities:
        return 0.5
    haystack = str(text or "").lower()
    hits = sum(1 for entity in clean_entities if entity in haystack)
    if hits == 0:
        return 0.0
    return clamp_score(hits / len(clean_entities))


def compute_fact_quality_score(
    evidence_type: str,
    importance: Any = 0.0,
    status: Any = None,
    ddl: Any = None,
    current_time: Any = None,
) -> float:
    importance_score = clamp_score(importance)
    if evidence_type == "original_fact":
        return clamp_score(0.70 + importance_score * 0.30)

    if evidence_type == "derived_fact":
        now = parse_time_value(current_time) or datetime.now(timezone.utc)
        ddl_time = parse_time_value(ddl)
        expired = ddl_time is not None and ddl_time < now
        if expired:
            return 0.20
        try:
            stable = int(status or 0) == 1
        except (TypeError, ValueError):
            stable = False
        if stable:
            return min(0.60 + importance_score * 0.30, 0.95)
        return min(0.40 + importance_score * 0.20, 0.70)

    return 0.5


def compute_fact_score(
    retrieval_score: float,
    entities: Iterable[str],
    content: str,
    evidence_type: str,
    importance: Any = 0.0,
    status: Any = None,
    ddl: Any = None,
    time_constraint: Optional[Dict[str, Any]] = None,
    valid_time: Any = None,
    create_time: Any = None,
    current_time: Any = None,
) -> float:
    entity_score = compute_entity_match_score(entities, content)
    quality_score = compute_fact_quality_score(evidence_type, importance, status, ddl, current_time)
    time_score = compute_time_score(time_constraint, valid_time)
    return clamp_score(
        clamp_score(retrieval_score) * FACT_SCORE_WEIGHTS["retrieval_score"]
        + entity_score * FACT_SCORE_WEIGHTS["entity_match_score"]
        + quality_score * FACT_SCORE_WEIGHTS["fact_quality_score"]
        + time_score * FACT_SCORE_WEIGHTS["time_score"]
    )


def compute_entity_score(
    query_text: str,
    query_entity: str,
    entity_name: str,
    entity_prop: str,
    create_time: Any = None,
    current_time: Any = None,
) -> float:
    query = str(query_text or "").lower()
    expected = str(query_entity or "").lower()
    name = str(entity_name or "").lower()
    if name and name in query:
        name_match = 1.0
    elif expected and (expected in name or name in expected):
        name_match = 0.7
    else:
        name_match = 0.0

    type_scores = {
        "person": 1.0,
        "organization": 0.9,
        "location": 0.85,
        "object": 0.75,
        "pet": 0.75,
    }
    type_score = type_scores.get(str(entity_prop or "").lower(), 0.5)

    created = parse_time_value(create_time)
    now = parse_time_value(current_time) or datetime.now(timezone.utc)
    if created is None:
        recency_score = 0.5
    else:
        age_days = max((now - created).days, 0)
        recency_score = clamp_score(1.0 / (1.0 + math.log1p(age_days) / 5.0))

    return clamp_score(name_match * 0.60 + type_score * 0.20 + recency_score * 0.20)


def compute_path_fact_quality_score(
    original_importance: Any = 0.0,
    original_confidence: Any = 0,
    derived_importance: Any = None,
    derived_status: Any = None,
    derived_ddl: Any = None,
    current_time: Any = None,
) -> float:
    original_quality = clamp_score(0.55 + clamp_score(original_importance) * 0.30)
    try:
        confidence = float(original_confidence or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    original_quality = clamp_score(original_quality + min(confidence / 50.0, 0.15))
    if derived_importance is None and derived_status is None:
        return original_quality
    derived_quality = compute_fact_quality_score(
        "derived_fact",
        importance=derived_importance or 0.0,
        status=derived_status,
        ddl=derived_ddl,
        current_time=current_time,
    )
    return clamp_score(max(original_quality, derived_quality))


def compute_relation_score(
    start_entity_score: float,
    path_relevance_score: float,
    hop_score: float,
    path_fact_quality_score: float,
    source_score: float,
) -> float:
    return clamp_score(
        clamp_score(start_entity_score) * 0.25
        + clamp_score(path_relevance_score) * 0.25
        + clamp_score(hop_score) * 0.20
        + clamp_score(path_fact_quality_score) * 0.20
        + clamp_score(source_score) * 0.10
    )


def compute_edge_quality_score(
    is_valid: Any = True,
    fact: Any = "",
    source_fact_uuid: Any = None,
    source_chunk_uuid: Any = None,
    confidence: Any = None,
    importance: Any = None,
) -> float:
    if is_valid is False or str(is_valid).lower() == "false":
        return 0.0

    base = 0.90 if str(fact or "").strip() else 0.60
    source_boost = 0.0
    if source_fact_uuid:
        source_boost += 0.03
    if source_chunk_uuid:
        source_boost += 0.04

    try:
        confidence_score = clamp_score(float(confidence))
    except (TypeError, ValueError):
        confidence_score = 0.5
    try:
        importance_score = clamp_score(float(importance))
    except (TypeError, ValueError):
        importance_score = 0.5

    return clamp_score(base + source_boost + confidence_score * 0.02 + importance_score * 0.01)


def compute_relation_source_score(source_fact_uuid: Any = None, source_chunk_uuid: Any = None) -> float:
    if source_chunk_uuid:
        return 1.0
    if source_fact_uuid:
        return 0.8
    return 0.5


def compute_hop_score(hops: Any) -> float:
    try:
        hop_count = int(hops)
    except (TypeError, ValueError):
        hop_count = 1
    if hop_count <= 1:
        return 1.0
    if hop_count == 2:
        return 0.75
    return 0.5


def compute_semantic_edge_score(
    start_entity_score: float,
    end_entity_score: float,
    edge_retrieval_score: float,
    fact_relevance_score: float,
    edge_quality_score: float,
    time_score: float,
) -> float:
    return clamp_score(
        clamp_score(start_entity_score) * SEMANTIC_EDGE_SCORE_WEIGHTS["start_entity_score"]
        + clamp_score(end_entity_score) * SEMANTIC_EDGE_SCORE_WEIGHTS["end_entity_score"]
        + clamp_score(edge_retrieval_score) * SEMANTIC_EDGE_SCORE_WEIGHTS["edge_retrieval_score"]
        + clamp_score(fact_relevance_score) * SEMANTIC_EDGE_SCORE_WEIGHTS["fact_relevance_score"]
        + clamp_score(edge_quality_score) * SEMANTIC_EDGE_SCORE_WEIGHTS["edge_quality_score"]
        + clamp_score(time_score) * SEMANTIC_EDGE_SCORE_WEIGHTS["time_score"]
    )


def compute_semantic_path_score(
    start_entity_score: float,
    path_relevance_score: float,
    hop_score: float,
    edge_quality_score: float,
    source_score: float,
    time_score: float,
) -> float:
    return clamp_score(
        clamp_score(start_entity_score) * SEMANTIC_PATH_SCORE_WEIGHTS["start_entity_score"]
        + clamp_score(path_relevance_score) * SEMANTIC_PATH_SCORE_WEIGHTS["path_relevance_score"]
        + clamp_score(hop_score) * SEMANTIC_PATH_SCORE_WEIGHTS["hop_score"]
        + clamp_score(edge_quality_score) * SEMANTIC_PATH_SCORE_WEIGHTS["edge_quality_score"]
        + clamp_score(source_score) * SEMANTIC_PATH_SCORE_WEIGHTS["source_score"]
        + clamp_score(time_score) * SEMANTIC_PATH_SCORE_WEIGHTS["time_score"]
    )


def compute_vector_score(rerank_score: float, milvus_score: float) -> float:
    rerank = clamp_score(rerank_score)
    milvus = clamp_score(milvus_score)
    if rerank < milvus:
        return clamp_score(rerank * 0.45 + milvus * 0.55)
    return clamp_score(rerank * 0.80 + milvus * 0.20)


def compute_route_match_score(item: EvidenceItem, routes: Iterable[str]) -> float:
    route_set = {str(route) for route in routes or []}
    if item.source in route_set:
        return 1.0
    if item.source == "fact" and "relation" in route_set:
        return 0.6
    if item.source == "relation" and "fact" in route_set:
        return 0.6
    if item.source == "vector" and "fact" in route_set:
        return 0.6
    return 0.2


def compute_evidence_quality_score(item: EvidenceItem) -> float:
    if item.evidence_type == "original_fact":
        return 1.0
    if item.evidence_type in {"semantic_fact_edge", "semantic_fact_path"}:
        return clamp_score(item.metadata.get("edge_quality_score", 0.9))
    if item.evidence_type == "fact_entity_path":
        return 0.9 if item.path else 0.6
    if item.evidence_type == "derived_fact":
        status = item.metadata.get("status")
        ddl = item.metadata.get("ddl")
        if compute_fact_quality_score("derived_fact", item.metadata.get("importance", 0), status, ddl) <= 0.2:
            return 0.2
        try:
            return 0.85 if int(status or 0) == 1 else 0.2
        except (TypeError, ValueError):
            return 0.2
    if item.evidence_type == "chunk":
        return 0.7
    return 0.5


def compute_multi_source_support_score(sources: Iterable[str]) -> float:
    count = len({str(source) for source in sources or [] if source})
    if count >= 3:
        return 1.0
    if count == 2:
        return 0.6
    return 0.0


def compute_final_score(
    item: EvidenceItem,
    routes: Iterable[str],
    time_constraint: Optional[Dict[str, Any]] = None,
) -> float:
    route_score = compute_route_match_score(item, routes)
    quality_score = compute_evidence_quality_score(item)
    support_score = compute_multi_source_support_score(item.sources)
    time_score = compute_time_score(time_constraint, item.valid_time)
    final = (
        clamp_score(item.local_score) * FINAL_SCORE_WEIGHTS["local_score"]
        + route_score * FINAL_SCORE_WEIGHTS["route_match_score"]
        + quality_score * FINAL_SCORE_WEIGHTS["evidence_quality_score"]
        + support_score * FINAL_SCORE_WEIGHTS["multi_source_support_score"]
        + time_score * FINAL_SCORE_WEIGHTS["time_score"]
    )
    final_score_components = {
        "local_score": clamp_score(item.local_score),
        "route_match_score": route_score,
        "evidence_quality_score": quality_score,
        "multi_source_support_score": support_score,
        "time_score": time_score,
    }
    time_values = item.valid_time if isinstance(item.valid_time, list) else [item.valid_time]
    item.metadata["time_status"] = "unknown" if not any(
        parse_time_value(value) is not None for value in time_values
    ) else "known"
    item.metadata["final_score_formula"] = score_formula("final_score", FINAL_SCORE_WEIGHTS)
    item.metadata["final_score_parts"] = final_score_components
    item.metadata["final_score_components"] = final_score_components
    item.final_score = clamp_score(final)
    return item.final_score
