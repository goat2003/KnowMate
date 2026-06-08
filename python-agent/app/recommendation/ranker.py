from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from typing import Any
from urllib.parse import urlparse

from app.contracts import JsonDict
from app.recommendation.config import RecommendationSettings


POSITIVE_DIMENSIONS = [
    "keyword_match",
    "profile_topic",
    "milvus_similarity",
    "neo4j_related_topic",
    "source_quality",
    "freshness",
    "content_quality",
]
PENALTY_DIMENSIONS = ["duplicate_penalty", "negative_preference_penalty"]


@dataclass(slots=True)
class RankedArticle:
    article: JsonDict
    article_id: str
    keep: bool
    score: float
    rank_position: int
    score_breakdown: list[JsonDict]
    recommendation_reasons: list[str]
    rejection_reasons: list[str]
    issues: list[str]
    primary_topic: str


class RecommendationRanker:
    def __init__(self, settings: RecommendationSettings | None = None) -> None:
        self.settings = settings or RecommendationSettings()

    def rank(
        self,
        articles: list[JsonDict],
        profile: JsonDict | None = None,
        *,
        mcp_signals: dict[str, JsonDict] | None = None,
        now: datetime | None = None,
    ) -> list[RankedArticle]:
        profile = profile or {}
        mcp_signals = mcp_signals or {}
        now = now or datetime.now(timezone.utc)
        scored = [
            self._score_article(
                article,
                profile,
                mcp_signals.get(str(article.get("article_id", "")), {}),
                now,
            )
            for article in articles
        ]
        scored.sort(key=lambda item: (not item.keep, -item.score, item.article_id))
        reranked = self._apply_diversity(scored)
        for index, item in enumerate(reranked, start=1):
            item.rank_position = index
        return reranked

    def _score_article(self, article: JsonDict, profile: JsonDict, signals: JsonDict, now: datetime) -> RankedArticle:
        article_id = str(article.get("article_id", "")).strip()
        title = str(article.get("title", "")).strip()
        raw_text = str(article.get("raw_text", "")).strip()
        breakdown = [
            self._keyword_match(article, profile),
            self._profile_topic(article, profile),
            self._milvus_similarity(signals),
            self._neo4j_related_topic(article, signals),
            self._source_quality(article),
            self._freshness(article, now),
            self._duplicate_penalty(article, profile, signals),
            self._negative_preference_penalty(article, profile),
            self._content_quality(article),
        ]
        score = self._combine(breakdown)
        rejection_reasons: list[str] = []
        if not article_id:
            rejection_reasons.append("缺少 article_id")
        if not title:
            rejection_reasons.append("缺少标题")
        if not raw_text and not article.get("url"):
            rejection_reasons.append("缺少正文和 URL")
        for part in breakdown:
            if part["dimension"] == "duplicate_penalty" and part["normalized_score"] >= 10:
                rejection_reasons.append("历史重复惩罚达到上限")
            if part["dimension"] == "negative_preference_penalty" and part["normalized_score"] >= 10:
                rejection_reasons.append("负面偏好惩罚达到上限")
            if part["dimension"] == "content_quality" and part["normalized_score"] <= 0:
                rejection_reasons.append("内容质量过低")
        keep = score >= self.settings.min_keep_score and not rejection_reasons
        issues = [] if keep else ["filtered_out"]
        return RankedArticle(
            article=article,
            article_id=article_id,
            keep=keep,
            score=round(score, 4),
            rank_position=0,
            score_breakdown=breakdown,
            recommendation_reasons=self._recommendation_reasons(breakdown),
            rejection_reasons=rejection_reasons or ([] if keep else [f"综合分低于最低保留分 {self.settings.min_keep_score}"]),
            issues=issues,
            primary_topic=self._primary_topic(article, breakdown),
        )

    def _combine(self, breakdown: list[JsonDict]) -> float:
        positive_total = 0.0
        positive_weight = 0.0
        penalty_total = 0.0
        penalty_weight = 0.0
        for part in breakdown:
            weight = max(float(part["weight"]), 0.0)
            if part["dimension"] in POSITIVE_DIMENSIONS and part["available"]:
                positive_total += part["normalized_score"] * weight
                positive_weight += weight
            if part["dimension"] in PENALTY_DIMENSIONS:
                penalty_total += part["normalized_score"] * weight
                penalty_weight += weight
        if positive_weight <= 0:
            return 0.0
        positive_score = positive_total / positive_weight
        penalty = penalty_total / penalty_weight if penalty_weight > 0 else 0.0
        return min(10.0, max(0.0, positive_score - penalty))

    def _part(self, dimension: str, score: float, evidence: list[str] | None = None, available: bool = True) -> JsonDict:
        weight = max(float(self.settings.weights.get(dimension, 0.0)), 0.0)
        normalized = min(10.0, max(0.0, float(score)))
        return {
            "dimension": dimension,
            "available": available,
            "raw_score": round(float(score), 4) if available else 0.0,
            "normalized_score": round(normalized, 4) if available else 0.0,
            "weight": weight,
            "contribution": round(normalized * weight, 4) if available else 0.0,
            "evidence": evidence or [],
        }

    def _keyword_match(self, article: JsonDict, profile: JsonDict) -> JsonDict:
        words = _terms(profile.get("keywords")) + _terms(profile.get("interests")) + _terms(profile.get("preferred_tags"))
        title = str(article.get("title", "")).lower()
        text = str(article.get("raw_text", "")).lower()
        tags = [str(tag).lower() for tag in article.get("tags", [])]
        score = 0.0
        hits: list[str] = []
        for word in dict.fromkeys(words):
            needle = word.lower()
            if not needle:
                continue
            if needle in title:
                score += 5.0
                hits.append(word)
            elif needle in tags:
                score += 2.5
                hits.append(word)
            elif needle in text:
                score += 1.5
                hits.append(word)
        return self._part("keyword_match", min(score, 10.0), hits)

    def _profile_topic(self, article: JsonDict, profile: JsonDict) -> JsonDict:
        topics = _weighted_terms(profile.get("topics"))
        if not topics:
            return self._part("profile_topic", 0.0, ["profile_topics_unavailable"], available=False)
        haystack = _article_text(article)
        hits: list[str] = []
        score = 0.0
        for topic, weight in topics.items():
            if topic.lower() in haystack:
                score += min(max(weight, 0.0), 1.0) * 10.0
                hits.append(f"{topic}:{weight:g}")
        return self._part("profile_topic", min(score, 10.0), hits)

    def _milvus_similarity(self, signals: JsonDict) -> JsonDict:
        matches = signals.get("milvus_matches")
        if matches is None:
            return self._part("milvus_similarity", 0.0, ["milvus_unavailable"], available=False)
        best = max((_float(match.get("score")) for match in matches if isinstance(match, dict)), default=0.0)
        return self._part("milvus_similarity", best * 10.0, [f"best:{best:g}"] if best else [])

    def _neo4j_related_topic(self, article: JsonDict, signals: JsonDict) -> JsonDict:
        topics = signals.get("neo4j_topics")
        if topics is None:
            return self._part("neo4j_related_topic", 0.0, ["neo4j_unavailable"], available=False)
        haystack = _article_text(article)
        score = 0.0
        hits: list[str] = []
        for item in topics:
            name = str(item.get("name", "")) if isinstance(item, dict) else str(item)
            weight = _float(item.get("score"), 0.7) if isinstance(item, dict) else 0.7
            if name and name.lower() in haystack:
                score += weight * 10.0
                hits.append(name)
        return self._part("neo4j_related_topic", min(score, 10.0), hits)

    def _source_quality(self, article: JsonDict) -> JsonDict:
        source = str(article.get("source", "")).lower()
        host = urlparse(str(article.get("url", ""))).hostname or ""
        value = self.settings.source_quality.get(source)
        if value is None:
            value = self.settings.source_quality.get(host.lower(), self.settings.source_quality_default)
        return self._part("source_quality", value, [source or host or "default"])

    def _freshness(self, article: JsonDict, now: datetime) -> JsonDict:
        published_at = str(article.get("published_at", "")).strip()
        if not published_at:
            return self._part("freshness", 5.0, ["missing_published_at"])
        try:
            parsed = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError:
            return self._part("freshness", 5.0, ["invalid_published_at"])
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age_days = max((now - parsed).total_seconds() / 86400.0, 0.0)
        if age_days >= self.settings.freshness.max_age_days:
            return self._part("freshness", 0.0, [f"age_days:{age_days:.1f}"])
        score = 10.0 * math.pow(0.5, age_days / self.settings.freshness.half_life_days)
        return self._part("freshness", score, [f"age_days:{age_days:.1f}"])

    def _duplicate_penalty(self, article: JsonDict, profile: JsonDict, signals: JsonDict) -> JsonDict:
        penalty = 0.0
        evidence: list[str] = []
        url = str(article.get("url", "")).strip().lower()
        title = str(article.get("title", "")).strip().lower()
        if url and url in {item.lower() for item in _terms(profile.get("seen_urls"))}:
            penalty = max(penalty, self.settings.duplicate.same_url_penalty)
            evidence.append("seen_url")
        if title and title in {item.lower() for item in _terms(profile.get("seen_titles"))}:
            penalty = max(penalty, self.settings.duplicate.same_title_penalty)
            evidence.append("seen_title")
        for match in signals.get("milvus_matches", []) or []:
            if isinstance(match, dict) and _float(match.get("score")) >= self.settings.duplicate.similar_memory_penalty_threshold:
                penalty = max(penalty, 8.0)
                evidence.append("similar_memory")
        return self._part("duplicate_penalty", penalty, evidence)

    def _negative_preference_penalty(self, article: JsonDict, profile: JsonDict) -> JsonDict:
        negatives = _terms(profile.get("negative_keywords")) + _terms(profile.get("negative_topics")) + _terms(profile.get("negative_preferences"))
        disliked_sources = {item.lower() for item in _terms(profile.get("disliked_sources"))}
        haystack = _article_text(article)
        hits = [word for word in dict.fromkeys(negatives) if word.lower() in haystack]
        source = str(article.get("source", "")).lower()
        if source and source in disliked_sources:
            hits.append(f"source:{source}")
        penalty = min(len(hits) * self.settings.negative_preferences.penalty_per_match, self.settings.negative_preferences.max_penalty)
        return self._part("negative_preference_penalty", penalty, hits)

    def _content_quality(self, article: JsonDict) -> JsonDict:
        title = str(article.get("title", "")).strip()
        raw_text = str(article.get("raw_text", "")).strip()
        score = 0.0
        evidence: list[str] = []
        if title:
            score += 2.5
            evidence.append("has_title")
        if article.get("url"):
            score += 1.5
            evidence.append("has_url")
        if len(raw_text) >= 400:
            score += 4.0
            evidence.append("long_text")
        elif len(raw_text) >= 80:
            score += 2.5
            evidence.append("enough_text")
        elif raw_text:
            score += 2.0
            evidence.append("short_text")
        if article.get("tags"):
            score += 1.0
            evidence.append("has_tags")
        if str(article.get("fetch_status", "")).lower() == "failed":
            score -= 3.0
            evidence.append("fetch_failed")
        return self._part("content_quality", score, evidence)

    def _recommendation_reasons(self, breakdown: list[JsonDict]) -> list[str]:
        reasons: list[str] = []
        for part in breakdown:
            if part["dimension"] in PENALTY_DIMENSIONS or not part["available"]:
                continue
            if part["normalized_score"] >= 7 and part["evidence"]:
                reasons.append(f"{part['dimension']} 命中：{', '.join(part['evidence'][:3])}")
        return reasons or ["综合评分达到推荐阈值"]

    def _primary_topic(self, article: JsonDict, breakdown: list[JsonDict]) -> str:
        tags = [str(tag).strip() for tag in article.get("tags", []) if str(tag).strip()]
        if tags:
            return tags[0].lower()
        for part in breakdown:
            if part["dimension"] in {"profile_topic", "neo4j_related_topic", "keyword_match"} and part["evidence"]:
                return str(part["evidence"][0]).split(":")[0].lower()
        return str(article.get("source", "") or "unknown").lower()

    def _apply_diversity(self, items: list[RankedArticle]) -> list[RankedArticle]:
        kept = [item for item in items if item.keep]
        rejected = [item for item in items if not item.keep]
        selected: list[RankedArticle] = []
        remaining = kept[:]
        while remaining:
            index = self._next_diverse_index(selected, remaining)
            selected.append(remaining.pop(index))
        return selected + rejected

    def _next_diverse_index(self, selected: list[RankedArticle], remaining: list[RankedArticle]) -> int:
        if not selected:
            return 0
        window = selected[-self.settings.diversity.topic_window_size :]
        next_size = len(window) + 1
        max_consecutive = self.settings.diversity.max_consecutive_same_topic
        recent = selected[-max_consecutive:]
        candidates: list[tuple[int, float, int]] = []
        for index, item in enumerate(remaining):
            hard_violations = 0
            if len(recent) == max_consecutive and all(prev.primary_topic == item.primary_topic for prev in recent):
                hard_violations += 1
            topic_count = sum(1 for prev in window if prev.primary_topic == item.primary_topic) + 1
            source = str(item.article.get("source", "")).lower()
            source_count = sum(1 for prev in window if str(prev.article.get("source", "")).lower() == source) + 1
            if topic_count / next_size > self.settings.diversity.max_same_topic_ratio:
                hard_violations += 1
            if source and source_count / next_size > self.settings.diversity.max_same_source_ratio:
                hard_violations += 1
            scarcity_penalty = topic_count + source_count * 0.5
            candidates.append((hard_violations, scarcity_penalty, index))
        candidates.sort(key=lambda pair: (pair[0], pair[1], -remaining[pair[2]].score, remaining[pair[2]].article_id))
        return candidates[0][2]


def _article_text(article: JsonDict) -> str:
    tags = " ".join(str(tag) for tag in article.get("tags", []))
    return f"{article.get('title', '')} {article.get('raw_text', '')} {tags}".lower()


def _terms(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, dict):
        return [str(key).strip() for key in raw if str(key).strip()]
    text = str(raw).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    if isinstance(parsed, dict):
        return [str(key).strip() for key in parsed if str(key).strip()]
    return [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]


def _weighted_terms(raw: object) -> dict[str, float]:
    if isinstance(raw, dict):
        return {str(key).strip(): _float(value, 1.0) for key, value in raw.items() if str(key).strip()}
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return {str(key).strip(): _float(value, 1.0) for key, value in parsed.items() if str(key).strip()}
    result: dict[str, float] = {}
    for term in _terms(text):
        if ":" in term:
            name, value = term.split(":", 1)
            result[name.strip()] = _float(value, 1.0)
        else:
            result[term] = 1.0
    return result


def _float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
