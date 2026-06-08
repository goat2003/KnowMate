from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_WEIGHTS = {
    "keyword_match": 1.0,
    "profile_topic": 1.2,
    "milvus_similarity": 1.0,
    "neo4j_related_topic": 0.9,
    "source_quality": 0.8,
    "freshness": 0.7,
    "duplicate_penalty": 1.0,
    "negative_preference_penalty": 1.0,
    "content_quality": 1.1,
}


@dataclass(slots=True)
class DiversitySettings:
    max_same_source_ratio: float = 0.5
    max_same_topic_ratio: float = 0.5
    max_consecutive_same_topic: int = 2
    topic_window_size: int = 5


@dataclass(slots=True)
class FreshnessSettings:
    half_life_days: float = 14.0
    max_age_days: float = 90.0


@dataclass(slots=True)
class DuplicateSettings:
    same_url_penalty: float = 10.0
    same_title_penalty: float = 7.0
    similar_memory_penalty_threshold: float = 0.92


@dataclass(slots=True)
class NegativePreferenceSettings:
    penalty_per_match: float = 2.0
    max_penalty: float = 6.0


@dataclass(slots=True)
class RecommendationSettings:
    min_keep_score: float = 5.0
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    diversity: DiversitySettings = field(default_factory=DiversitySettings)
    freshness: FreshnessSettings = field(default_factory=FreshnessSettings)
    source_quality_default: float = 6.0
    source_quality: dict[str, float] = field(default_factory=dict)
    milvus_minimum_score: float = 0.75
    duplicate: DuplicateSettings = field(default_factory=DuplicateSettings)
    negative_preferences: NegativePreferenceSettings = field(default_factory=NegativePreferenceSettings)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "RecommendationSettings":
        raw = raw or {}
        weights = dict(DEFAULT_WEIGHTS)
        for key, value in dict(raw.get("weights", {})).items():
            weights[str(key)] = max(_float(value, weights.get(str(key), 0.0)), 0.0)

        diversity_raw = raw.get("diversity", {}) or {}
        freshness_raw = raw.get("freshness", {}) or {}
        source_raw = raw.get("source_quality", {}) or {}
        duplicate_raw = raw.get("duplicate", {}) or {}
        negative_raw = raw.get("negative_preferences", {}) or {}
        milvus_raw = raw.get("milvus", {}) or {}

        return cls(
            min_keep_score=_float(raw.get("min_keep_score"), 5.0),
            weights=weights,
            diversity=DiversitySettings(
                max_same_source_ratio=_float(diversity_raw.get("max_same_source_ratio"), 0.5),
                max_same_topic_ratio=_float(diversity_raw.get("max_same_topic_ratio"), 0.5),
                max_consecutive_same_topic=max(int(_float(diversity_raw.get("max_consecutive_same_topic"), 2)), 1),
                topic_window_size=max(int(_float(diversity_raw.get("topic_window_size"), 5)), 1),
            ),
            freshness=FreshnessSettings(
                half_life_days=max(_float(freshness_raw.get("half_life_days"), 14.0), 0.1),
                max_age_days=max(_float(freshness_raw.get("max_age_days"), 90.0), 1.0),
            ),
            source_quality_default=_float(source_raw.get("default_score"), 6.0),
            source_quality={str(key).lower(): _float(value, 0.0) for key, value in dict(source_raw.get("sources", {})).items()},
            milvus_minimum_score=_float(milvus_raw.get("minimum_score"), 0.75),
            duplicate=DuplicateSettings(
                same_url_penalty=_float(duplicate_raw.get("same_url_penalty"), 10.0),
                same_title_penalty=_float(duplicate_raw.get("same_title_penalty"), 7.0),
                similar_memory_penalty_threshold=_float(duplicate_raw.get("similar_memory_penalty_threshold"), 0.92),
            ),
            negative_preferences=NegativePreferenceSettings(
                penalty_per_match=_float(negative_raw.get("penalty_per_match"), 2.0),
                max_penalty=_float(negative_raw.get("max_penalty"), 6.0),
            ),
        )


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
