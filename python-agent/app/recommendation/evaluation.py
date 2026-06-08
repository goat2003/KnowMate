from __future__ import annotations

import math
from typing import Any


def evaluate_ranked_items(ranked: list[dict[str, Any]], k: int = 5) -> dict[str, float | int]:
    k = max(int(k), 1)
    top = ranked[:k]
    positives = sum(1 for item in ranked if int(item.get("label", 0)) > 0)
    hits = sum(1 for item in top if int(item.get("label", 0)) > 0)
    dcg = _dcg([float(item.get("relevance", item.get("label", 0))) for item in top])
    ideal = sorted((float(item.get("relevance", item.get("label", 0))) for item in ranked), reverse=True)[:k]
    ideal_dcg = _dcg(ideal)
    topics = {str(item.get("topic") or item.get("primary_topic") or "unknown") for item in top}

    return {
        "k": k,
        "precision_at_k": round(hits / k, 6),
        "recall_at_k": round(hits / positives, 6) if positives else 0.0,
        "ndcg_at_k": round(dcg / ideal_dcg, 6) if ideal_dcg else 0.0,
        "diversity": round(len(topics) / len(top), 6) if top else 0.0,
        "duplicate_rate": round(_duplicate_rate(top), 6),
        "items_evaluated": len(ranked),
    }


def _dcg(relevances: list[float]) -> float:
    return sum(((2**rel - 1) / math.log2(index + 2)) for index, rel in enumerate(relevances))


def _duplicate_rate(items: list[dict[str, Any]]) -> float:
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    duplicates = 0
    for item in items:
        duplicated = False
        for value, seen in [
            (str(item.get("article_id", "")).strip().lower(), seen_ids),
            (str(item.get("url", "")).strip().lower(), seen_urls),
            (str(item.get("title", "")).strip().lower(), seen_titles),
        ]:
            if not value:
                continue
            if value in seen:
                duplicated = True
            seen.add(value)
        if duplicated:
            duplicates += 1
    return duplicates / len(items) if items else 0.0
