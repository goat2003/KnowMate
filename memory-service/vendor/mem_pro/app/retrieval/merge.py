"""Evidence merge and deduplication."""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional

from app.retrieval.models import EvidenceItem, clamp_score, json_safe


def _path_key(item: EvidenceItem) -> Optional[str]:
    if not item.path:
        return None
    return json.dumps(json_safe(item.path), ensure_ascii=False, sort_keys=True)


def evidence_key(item: EvidenceItem) -> Optional[str]:
    if item.ori_fact_uuid:
        return f"ori:{item.ori_fact_uuid}"
    if item.fact_uuid:
        return f"fact:{item.fact_uuid}"
    relation_uuid = item.metadata.get("relation_uuid")
    if relation_uuid:
        return f"relation:{relation_uuid}"
    relation_uuids = item.metadata.get("relation_uuids")
    if relation_uuids:
        return "relation_path:" + "|".join(str(value) for value in relation_uuids if value)
    path_key = item.metadata.get("path_key")
    if path_key:
        return f"path:{path_key}"
    if item.chunk_uuid is not None and item.chunk_content_index is not None:
        return f"chunk:{item.chunk_uuid}:{item.chunk_content_index}"
    if item.chunk_uuid is not None:
        return f"chunk:{item.chunk_uuid}"
    path = _path_key(item)
    if path:
        return f"path:{path}"
    return None


def content_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return clamp_score(SequenceMatcher(None, left, right).ratio())


def _choose_content(current: str, candidate: str) -> str:
    if not current:
        return candidate
    if not candidate:
        return current
    if len(candidate) < len(current) and len(candidate) >= 12:
        return candidate
    return current


def _is_relation_item(item: EvidenceItem) -> bool:
    return (
        item.source == "relation"
        or "relation" in item.sources
        or bool(item.metadata.get("relation_uuid"))
        or bool(item.metadata.get("relation_uuids"))
        or item.evidence_type in {"semantic_fact_edge", "semantic_fact_path"}
    )


def merge_two(left: EvidenceItem, right: EvidenceItem) -> EvidenceItem:
    left_is_relation = _is_relation_item(left)
    right_is_relation = _is_relation_item(right)
    if right.local_score > left.local_score and not (left_is_relation and not right_is_relation):
        left.source = right.source
        left.local_score = right.local_score
        left.evidence_type = right.evidence_type or left.evidence_type

    if left_is_relation and not right_is_relation:
        left.content = left.content or right.content
    elif right_is_relation and not left_is_relation:
        left.content = right.content or left.content
        left.source = right.source
        left.evidence_type = right.evidence_type or left.evidence_type
    else:
        left.content = _choose_content(left.content, right.content)
    left.sources = sorted(set(left.sources) | set(right.sources) | {left.source, right.source})
    left.final_score = max(left.final_score, right.final_score)

    for attr in (
        "ori_fact_uuid",
        "chunk_uuid",
        "fact_uuid",
        "chunk_content_index",
        "entity_uuid",
        "valid_time",
        "create_time",
    ):
        if getattr(left, attr) is None and getattr(right, attr) is not None:
            setattr(left, attr, getattr(right, attr))

    if not left.path and right.path:
        left.path = right.path

    route_scores = dict(left.metadata.get("route_scores") or {})
    route_scores[right.source] = max(
        clamp_score(route_scores.get(right.source, 0.0)),
        clamp_score(right.local_score),
    )
    route_scores[left.source] = max(
        clamp_score(route_scores.get(left.source, 0.0)),
        clamp_score(left.local_score),
    )
    route_raw_hit_ranks = dict(left.metadata.get("route_raw_hit_ranks") or {})
    for source, rank in (right.metadata.get("route_raw_hit_ranks") or {}).items():
        try:
            rank_value = int(rank)
        except (TypeError, ValueError):
            continue
        current = route_raw_hit_ranks.get(source)
        try:
            current_value = int(current)
        except (TypeError, ValueError):
            current_value = None
        if current_value is None or rank_value < current_value:
            route_raw_hit_ranks[source] = rank_value
    left.metadata.update({k: v for k, v in right.metadata.items() if k not in left.metadata})
    left.metadata["route_scores"] = route_scores
    if route_raw_hit_ranks:
        left.metadata["route_raw_hit_ranks"] = route_raw_hit_ranks
    route_retrieval_scores = dict(left.metadata.get("route_retrieval_scores") or {})
    for source, score in (right.metadata.get("route_retrieval_scores") or {}).items():
        try:
            score_value = float(score)
        except (TypeError, ValueError):
            continue
        try:
            current_value = float(route_retrieval_scores.get(source))
        except (TypeError, ValueError):
            current_value = None
        if current_value is None or score_value > current_value:
            route_retrieval_scores[source] = score_value
    if route_retrieval_scores:
        left.metadata["route_retrieval_scores"] = route_retrieval_scores
    sub_query_indexes = set()
    for item in (left, right):
        values = item.metadata.get("sub_query_indices")
        if not isinstance(values, (list, tuple, set)):
            values = [item.metadata.get("sub_query_index")]
        for value in values:
            try:
                sub_query_indexes.add(int(value))
            except (TypeError, ValueError):
                continue
    if sub_query_indexes:
        left.metadata["sub_query_indices"] = sorted(sub_query_indexes)
    left.metadata["merged_count"] = int(left.metadata.get("merged_count", 1)) + int(
        right.metadata.get("merged_count", 1)
    )
    return left


def merge_evidence_items(items: Iterable[EvidenceItem], similarity_threshold: float = 0.92) -> List[EvidenceItem]:
    keyed: Dict[str, EvidenceItem] = {}
    unkeyed: List[EvidenceItem] = []

    for item in items:
        if not item or not item.content:
            continue
        key = evidence_key(item)
        if key:
            if key in keyed:
                keyed[key] = merge_two(keyed[key], item)
            else:
                item.metadata.setdefault("route_scores", {item.source: item.local_score})
                keyed[key] = item
            continue

        merged = False
        for idx, existing in enumerate(unkeyed):
            if content_similarity(existing.content, item.content) >= similarity_threshold:
                unkeyed[idx] = merge_two(existing, item)
                merged = True
                break
        if not merged:
            item.metadata.setdefault("route_scores", {item.source: item.local_score})
            unkeyed.append(item)

    merged_items = list(keyed.values()) + unkeyed

    # A vector hit may initially be keyed by chunk, while a fact hit is keyed by
    # ori_fact_uuid. Do a second pass so chunk rows with fact_uuid merge into the
    # corresponding OriginalFact evidence.
    by_ori: Dict[str, EvidenceItem] = {}
    for item in merged_items:
        if not item.ori_fact_uuid or _is_relation_item(item):
            continue
        by_ori[item.ori_fact_uuid] = item
    result: List[EvidenceItem] = []
    consumed = set()
    for item in merged_items:
        if id(item) in consumed:
            continue
        if _is_relation_item(item):
            source_fact_uuid = item.metadata.get("source_fact_uuid") or item.fact_uuid or item.ori_fact_uuid
            if source_fact_uuid in by_ori:
                item.sources = sorted(set(item.sources) | {"fact", "relation"})
                route_scores = dict(item.metadata.get("route_scores") or {})
                route_scores.setdefault("fact", by_ori[source_fact_uuid].local_score)
                route_scores.setdefault("relation", item.local_score)
                item.metadata["route_scores"] = route_scores
                item.metadata["same_source_fact_uuid"] = source_fact_uuid
            result.append(item)
            continue
        if item.fact_uuid and item.fact_uuid in by_ori and by_ori[item.fact_uuid] is not item:
            target = by_ori[item.fact_uuid]
            merge_two(target, item)
            consumed.add(id(item))
            continue
        result.append(item)

    return sorted(result, key=lambda evidence: evidence.local_score, reverse=True)
