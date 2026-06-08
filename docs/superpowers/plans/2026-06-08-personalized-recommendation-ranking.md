# Personalized Recommendation Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Python Filter Agent 升级为可解释、可配置、可降级、可重复测试的个性化推荐排序系统，并补齐 gRPC 输出和离线评估能力。

**Architecture:** 新增 `app/recommendation/` 作为独立排序模块，Filter Agent 只负责收集本地文章字段与 MCP 信号并调用排序器。排序器输出 0 到 10 综合分、维度明细、推荐/拒绝原因和稳定排名；protobuf/gRPC 追加解释字段，GoFrame 最小接入保持 posts 落库逻辑不变。

**Tech Stack:** Python 3.10+、unittest/pytest、protobuf/gRPC、Go 1.x、PowerShell 验证脚本。

---

## File Structure

- Create: `python-agent/app/recommendation/__init__.py`
  - 导出推荐配置、排序器和评估函数。
- Create: `python-agent/app/recommendation/config.py`
  - 定义 `RecommendationSettings`、默认权重、多样性与时效配置。
- Create: `python-agent/app/recommendation/ranker.py`
  - 实现评分维度、综合分、推荐/拒绝原因、多样性重排。
- Create: `python-agent/app/recommendation/evaluation.py`
  - 实现 Precision@K、Recall@K、NDCG@K、多样性、重复率。
- Create: `python-agent/scripts/evaluate_recommendations.py`
  - 离线评估 CLI。
- Create: `python-agent/tests/test_recommendation_ranker.py`
  - 覆盖评分、降级、多样性、确定性。
- Create: `python-agent/tests/test_recommendation_evaluation.py`
  - 覆盖离线指标。
- Modify: `python-agent/app/config.py`
  - 加载 `recommendation` 配置段。
- Modify: `python-agent/config.yaml`
  - 增加默认推荐排序配置示例。
- Modify: `python-agent/app/agents/filter_agent.py`
  - 接入新排序器，替换旧 `_score_article` 主路径。
- Modify: `python-agent/app/workflow/graph.py`
  - 在 `process_articles` 输出中透传新解释字段。
- Modify: `python-agent/app/workflow/state.py`
  - 更新 `article_results` 字段说明。
- Modify: `python-agent/app/grpc_server.py`
  - 将评分明细、原因和排名写入 protobuf 响应。
- Modify: `python-agent/tests/test_workflow.py`
  - 增加 workflow/gRPC 解释字段断言，保留旧流程断言。
- Modify: `shared/proto/agent.proto`
  - 新增 `ScoreBreakdownItem` 和 `ArticleProcessResult` 追加字段。
- Modify: `proto/agent.proto`
  - 与 shared proto 保持一致。
- Modify generated: `python-agent/agent_pb2.py`
- Modify generated: `python-agent/agent_pb2_grpc.py`
- Modify generated: `goframe-backend/internal/agentpb/agent.pb.go`
- Modify generated: `goframe-backend/internal/agentpb/agent_grpc.pb.go`
- Modify: `goframe-backend/internal/agentpb/proto_contract_test.go`
  - 检查新增 protobuf 字段。
- Modify: `scripts/check_proto_contract.ps1`
  - Python 侧契约检查新增字段。
- Modify: `python-agent/app/skills/filter_skill.md`
  - 将输出说明从 0..1 简单分更新为 0..10 可解释推荐分。
- Modify: `README.md`
  - 增加推荐配置、离线评估命令和 proto 生成提示。

## Task 1: Recommendation Configuration

**Files:**
- Create: `python-agent/app/recommendation/__init__.py`
- Create: `python-agent/app/recommendation/config.py`
- Modify: `python-agent/app/config.py`
- Modify: `python-agent/config.yaml`
- Test: `python-agent/tests/test_recommendation_ranker.py`

- [ ] **Step 1: Write the failing configuration test**

Add to `python-agent/tests/test_recommendation_ranker.py`:

```python
import unittest

from app.config import Settings
from app.recommendation import RecommendationSettings


class RecommendationSettingsTest(unittest.TestCase):
    def test_default_recommendation_settings_include_all_dimensions(self) -> None:
        settings = RecommendationSettings()

        self.assertEqual(settings.min_keep_score, 5.0)
        self.assertEqual(
            set(settings.weights),
            {
                "keyword_match",
                "profile_topic",
                "milvus_similarity",
                "neo4j_related_topic",
                "source_quality",
                "freshness",
                "duplicate_penalty",
                "negative_preference_penalty",
                "content_quality",
            },
        )
        self.assertGreater(settings.weights["content_quality"], 0)

    def test_settings_accept_recommendation_config(self) -> None:
        settings = Settings(
            recommendation=RecommendationSettings(
                min_keep_score=6.5,
                weights={"keyword_match": 2.0, "content_quality": 1.0},
            )
        )

        self.assertEqual(settings.recommendation.min_keep_score, 6.5)
        self.assertEqual(settings.recommendation.weights["keyword_match"], 2.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_recommendation_ranker.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.recommendation'` or `Settings.__init__() got an unexpected keyword argument 'recommendation'`.

- [ ] **Step 3: Add recommendation config implementation**

Create `python-agent/app/recommendation/__init__.py`:

```python
from app.recommendation.config import DiversitySettings, FreshnessSettings, RecommendationSettings

__all__ = ["DiversitySettings", "FreshnessSettings", "RecommendationSettings"]
```

Create `python-agent/app/recommendation/config.py`:

```python
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
            weights[str(key)] = max(float(value), 0.0)
        diversity_raw = raw.get("diversity", {}) or {}
        freshness_raw = raw.get("freshness", {}) or {}
        source_raw = raw.get("source_quality", {}) or {}
        duplicate_raw = raw.get("duplicate", {}) or {}
        negative_raw = raw.get("negative_preferences", {}) or {}
        return cls(
            min_keep_score=float(raw.get("min_keep_score", 5.0)),
            weights=weights,
            diversity=DiversitySettings(
                max_same_source_ratio=float(diversity_raw.get("max_same_source_ratio", 0.5)),
                max_same_topic_ratio=float(diversity_raw.get("max_same_topic_ratio", 0.5)),
                max_consecutive_same_topic=max(int(diversity_raw.get("max_consecutive_same_topic", 2)), 1),
                topic_window_size=max(int(diversity_raw.get("topic_window_size", 5)), 1),
            ),
            freshness=FreshnessSettings(
                half_life_days=max(float(freshness_raw.get("half_life_days", 14.0)), 0.1),
                max_age_days=max(float(freshness_raw.get("max_age_days", 90.0)), 1.0),
            ),
            source_quality_default=float(source_raw.get("default_score", 6.0)),
            source_quality={str(k).lower(): float(v) for k, v in dict(source_raw.get("sources", {})).items()},
            milvus_minimum_score=float((raw.get("milvus", {}) or {}).get("minimum_score", 0.75)),
            duplicate=DuplicateSettings(
                same_url_penalty=float(duplicate_raw.get("same_url_penalty", 10.0)),
                same_title_penalty=float(duplicate_raw.get("same_title_penalty", 7.0)),
                similar_memory_penalty_threshold=float(duplicate_raw.get("similar_memory_penalty_threshold", 0.92)),
            ),
            negative_preferences=NegativePreferenceSettings(
                penalty_per_match=float(negative_raw.get("penalty_per_match", 2.0)),
                max_penalty=float(negative_raw.get("max_penalty", 6.0)),
            ),
        )
```

Modify `python-agent/app/config.py`:

```python
from app.recommendation import RecommendationSettings
```

Add to `Settings`:

```python
recommendation: RecommendationSettings = field(default_factory=RecommendationSettings)
```

Add in `load_settings()` after `llm = raw.get("llm", {})`:

```python
recommendation = raw.get("recommendation", {})
```

Pass to `Settings(...)`:

```python
recommendation=RecommendationSettings.from_dict(recommendation),
```

Modify `python-agent/config.yaml` by adding the `recommendation:` block from the design spec.

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_recommendation_ranker.py -q
```

Expected: PASS.

## Task 2: Core Ranker Scoring

**Files:**
- Create: `python-agent/app/recommendation/ranker.py`
- Modify: `python-agent/app/recommendation/__init__.py`
- Test: `python-agent/tests/test_recommendation_ranker.py`

- [ ] **Step 1: Write failing ranker tests**

Append to `python-agent/tests/test_recommendation_ranker.py`:

```python
from datetime import datetime, timezone

from app.recommendation import RecommendationRanker


class RecommendationRankerScoringTest(unittest.TestCase):
    def test_ranker_returns_zero_to_ten_score_and_all_breakdown_dimensions(self) -> None:
        ranker = RecommendationRanker(RecommendationSettings())
        results = ranker.rank(
            [
                {
                    "article_id": "a1",
                    "url": "https://arxiv.org/abs/1",
                    "title": "AI workflow for knowledge agents",
                    "raw_text": "A practical article about AI workflow and knowledge management." * 4,
                    "source": "arxiv",
                    "published_at": "2026-06-01T00:00:00Z",
                    "tags": ["AI", "workflow"],
                }
            ],
            {"keywords": "AI,workflow", "topics": "AI:0.9,databases:0.2"},
            mcp_signals={"a1": {"milvus_matches": [{"score": 0.86}], "neo4j_topics": [{"name": "AI", "score": 0.9}]}},
            now=datetime(2026, 6, 8, tzinfo=timezone.utc),
        )

        item = results[0]
        self.assertTrue(item.keep)
        self.assertGreaterEqual(item.score, 0)
        self.assertLessEqual(item.score, 10)
        self.assertEqual(
            {part["dimension"] for part in item.score_breakdown},
            set(RecommendationSettings().weights),
        )
        self.assertTrue(item.recommendation_reasons)

    def test_negative_preferences_and_duplicates_can_reject_article(self) -> None:
        ranker = RecommendationRanker(RecommendationSettings(min_keep_score=5.0))
        results = ranker.rank(
            [
                {
                    "article_id": "a2",
                    "url": "https://example.com/seen",
                    "title": "Crypto giveaway marketing",
                    "raw_text": "Crypto giveaway marketing copy.",
                    "source": "spam",
                    "published_at": "2026-06-07T00:00:00Z",
                    "tags": ["crypto"],
                }
            ],
            {
                "keywords": "AI",
                "negative_keywords": "crypto,giveaway",
                "seen_urls": "https://example.com/seen",
            },
            now=datetime(2026, 6, 8, tzinfo=timezone.utc),
        )

        item = results[0]
        self.assertFalse(item.keep)
        self.assertIn("filtered_out", item.issues)
        self.assertTrue(item.rejection_reasons)

    def test_ranker_is_deterministic_for_equal_scores(self) -> None:
        ranker = RecommendationRanker(RecommendationSettings())
        articles = [
            {"article_id": "b", "title": "AI", "raw_text": "AI text" * 30, "source": "s1", "tags": ["AI"]},
            {"article_id": "a", "title": "AI", "raw_text": "AI text" * 30, "source": "s1", "tags": ["AI"]},
        ]

        first = [item.article_id for item in ranker.rank(articles, {"keywords": "AI"})]
        second = [item.article_id for item in ranker.rank(articles, {"keywords": "AI"})]

        self.assertEqual(first, second)
        self.assertEqual(first, ["a", "b"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_recommendation_ranker.py -q
```

Expected: FAIL with `ImportError: cannot import name 'RecommendationRanker'`.

- [ ] **Step 3: Implement ranking data structures and scoring**

Create `python-agent/app/recommendation/ranker.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
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
        scored = [self._score_article(article, profile, mcp_signals.get(str(article.get("article_id", "")), {}), now) for article in articles]
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
```

Implement helper methods in the same file:

```python
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
                score += 3.0
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
            score += 1.0
            evidence.append("short_text")
        if article.get("tags"):
            score += 1.0
            evidence.append("has_tags")
        if str(article.get("fetch_status", "")).lower() == "failed":
            score -= 3.0
            evidence.append("fetch_failed")
        return self._part("content_quality", score, evidence)
```

Add module helper functions and diversity methods from the design:

```python
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
        max_consecutive = self.settings.diversity.max_consecutive_same_topic
        recent = selected[-max_consecutive:]
        for index, item in enumerate(remaining):
            if len(recent) == max_consecutive and all(prev.primary_topic == item.primary_topic for prev in recent):
                continue
            return index
        return 0


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
```

Modify `python-agent/app/recommendation/__init__.py`:

```python
from app.recommendation.ranker import RankedArticle, RecommendationRanker
```

and add both names to `__all__`.

- [ ] **Step 4: Run ranker tests to verify they pass**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_recommendation_ranker.py -q
```

Expected: PASS.

## Task 3: Filter Agent Integration

**Files:**
- Modify: `python-agent/app/agents/filter_agent.py`
- Modify: `python-agent/app/workflow/graph.py`
- Modify: `python-agent/app/workflow/state.py`
- Modify: `python-agent/tests/test_workflow.py`
- Test: `python-agent/tests/test_workflow.py`

- [ ] **Step 1: Write failing workflow tests**

Add to `ArticleWorkflowTest` in `python-agent/tests/test_workflow.py`:

```python
    def test_filter_agent_outputs_explainable_recommendation_fields(self) -> None:
        workflow = ArticleWorkflow(Settings(mock_mcp=True))
        result = workflow.process_articles(
            {
                "run_id": "ranking-explain",
                "user_profile_snapshot": {"interests": "AI,workflow", "topics": "AI:1.0"},
                "mcp_policy": {
                    "mock_transport": True,
                    "enable_embedding": True,
                    "enable_milvus": True,
                    "enable_neo4j": True,
                },
                "articles": [
                    {
                        "article_id": "rank-a",
                        "url": "https://example.com/rank-a",
                        "title": "AI workflow notes",
                        "raw_text": "A practical AI workflow article with implementation details." * 5,
                        "source": "arxiv",
                        "published_at": "2026-06-01T00:00:00Z",
                        "tags": ["AI", "workflow"],
                    }
                ],
            }
        )

        item = result["results"][0]
        self.assertGreaterEqual(item["score"], 0)
        self.assertLessEqual(item["score"], 10)
        self.assertEqual(item["rank_position"], 1)
        self.assertTrue(item["score_breakdown"])
        self.assertTrue(item["recommendation_reasons"])
        self.assertEqual(item["rejection_reasons"], [])
```

- [ ] **Step 2: Run workflow test to verify it fails**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_workflow.py::ArticleWorkflowTest::test_filter_agent_outputs_explainable_recommendation_fields -q
```

Expected: FAIL with missing `rank_position` or `score_breakdown`.

- [ ] **Step 3: Inject recommendation settings into FilterAgent**

Modify `python-agent/app/agents/filter_agent.py` constructor:

```python
from app.recommendation import RecommendationRanker, RecommendationSettings
```

Add parameter:

```python
recommendation_settings: RecommendationSettings | None = None,
```

Set:

```python
self.ranker = RecommendationRanker(recommendation_settings)
```

Modify `ArticleWorkflow.__init__` in `python-agent/app/workflow/graph.py` when constructing `FilterAgent`:

```python
recommendation_settings=settings.recommendation,
```

- [ ] **Step 4: Replace per-article scoring with batch ranking**

In `FilterAgent.run`, keep MCP log collection per article but build:

```python
signals_by_article_id: dict[str, JsonDict] = {}
logs_by_article_id: dict[str, list[JsonDict]] = {}
```

For each article:

```python
article_id = str(article.get("article_id", ""))
logs_by_article_id[article_id] = logs
signals_by_article_id[article_id] = {
    "milvus_matches": related.result.get("matches") if milvus call succeeded else None,
    "neo4j_topics": context.result.get("topics") if neo4j call succeeded else None,
}
```

After MCP collection:

```python
ranked = self.ranker.rank(
    list(state.get("articles", [])),
    profile,
    mcp_signals=signals_by_article_id,
)
```

Build each result from `RankedArticle`:

```python
article_results.append(
    {
        "article": ranked_item.article,
        "article_id": ranked_item.article_id,
        "keep": ranked_item.keep,
        "score": ranked_item.score,
        "rank_position": ranked_item.rank_position,
        "score_breakdown": ranked_item.score_breakdown,
        "recommendation_reasons": ranked_item.recommendation_reasons,
        "rejection_reasons": ranked_item.rejection_reasons,
        "summary": "",
        "post_text": "",
        "check_pass": False,
        "issues": ranked_item.issues,
        "mcp_call_logs": logs_by_article_id.get(ranked_item.article_id, []),
        "filter_reasons": ranked_item.recommendation_reasons + ranked_item.rejection_reasons,
    }
)
```

Retain `_profile_keywords` only if still used by compatibility tests; otherwise remove `_score_article` after tests are green.

- [ ] **Step 5: Pass new fields through workflow output**

Modify `python-agent/app/workflow/graph.py` response item:

```python
"rank_position": int(item.get("rank_position", 0)),
"score_breakdown": list(item.get("score_breakdown", [])),
"recommendation_reasons": list(item.get("recommendation_reasons", [])),
"rejection_reasons": list(item.get("rejection_reasons", [])),
```

- [ ] **Step 6: Run workflow tests**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_workflow.py -q
```

Expected: PASS. If old assertions expect `score >= 0.5`, they still pass because new scores are `0..10`.

## Task 4: Protobuf and gRPC Explanation Fields

**Files:**
- Modify: `shared/proto/agent.proto`
- Modify: `proto/agent.proto`
- Modify generated: `python-agent/agent_pb2.py`
- Modify generated: `python-agent/agent_pb2_grpc.py`
- Modify generated: `goframe-backend/internal/agentpb/agent.pb.go`
- Modify generated: `goframe-backend/internal/agentpb/agent_grpc.pb.go`
- Modify: `python-agent/app/grpc_server.py`
- Modify: `python-agent/tests/test_workflow.py`
- Modify: `goframe-backend/internal/agentpb/proto_contract_test.go`
- Modify: `scripts/check_proto_contract.ps1`

- [ ] **Step 1: Write failing proto contract tests**

Modify `goframe-backend/internal/agentpb/proto_contract_test.go` result field list:

```go
for _, name := range []string{
    "article_id", "keep", "score", "summary", "post_text", "check_pass",
    "issues", "mcp_call_logs", "score_breakdown", "recommendation_reasons",
    "rejection_reasons", "rank_position",
} {
```

Add before ArticleProcessResult check:

```go
breakdown := file.Messages().ByName("ScoreBreakdownItem")
if breakdown == nil {
    t.Fatal("ScoreBreakdownItem is missing")
}
for _, name := range []string{"dimension", "available", "raw_score", "normalized_score", "weight", "contribution", "evidence"} {
    if breakdown.Fields().ByName(protoreflect.Name(name)) == nil {
        t.Fatalf("ScoreBreakdownItem.%s is missing", name)
    }
}
```

Modify `scripts/check_proto_contract.ps1` Python field list similarly.

- [ ] **Step 2: Run proto contract to verify it fails**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
.\scripts\check_proto_contract.ps1
```

Expected: FAIL because `ScoreBreakdownItem` or new result fields are missing.

- [ ] **Step 3: Extend proto files**

Add to both `shared/proto/agent.proto` and `proto/agent.proto` before `ArticleProcessResult`:

```proto
message ScoreBreakdownItem {
  string dimension = 1;
  bool available = 2;
  double raw_score = 3;
  double normalized_score = 4;
  double weight = 5;
  double contribution = 6;
  repeated string evidence = 7;
}
```

Append fields to `ArticleProcessResult`:

```proto
  repeated ScoreBreakdownItem score_breakdown = 9;
  repeated string recommendation_reasons = 10;
  repeated string rejection_reasons = 11;
  int32 rank_position = 12;
```

- [ ] **Step 4: Regenerate Python protobuf stubs**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
python -m grpc_tools.protoc -I shared/proto --python_out=python-agent --grpc_python_out=python-agent shared/proto/agent.proto
```

Expected: `python-agent/agent_pb2.py` and `python-agent/agent_pb2_grpc.py` updated.

- [ ] **Step 5: Regenerate Go protobuf stubs**

Run the repository's existing generation command if available. If none is scripted, use the installed protoc toolchain matching current generated files:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
protoc -I shared/proto --go_out=goframe-backend/internal/agentpb --go_opt=paths=source_relative --go-grpc_out=goframe-backend/internal/agentpb --go-grpc_opt=paths=source_relative shared/proto/agent.proto
```

If this writes to a nested unexpected path, stop and adjust the command before continuing. Do not hand-edit generated protobuf code unless generation is blocked and the user approves that fallback.

- [ ] **Step 6: Map gRPC response fields**

Add helper to `python-agent/app/grpc_server.py`:

```python
def _score_breakdown_to_proto(item: dict[str, Any]) -> agent_pb2.ScoreBreakdownItem:
    return agent_pb2.ScoreBreakdownItem(
        dimension=str(item.get("dimension", "")),
        available=bool(item.get("available", False)),
        raw_score=float(item.get("raw_score", 0)),
        normalized_score=float(item.get("normalized_score", 0)),
        weight=float(item.get("weight", 0)),
        contribution=float(item.get("contribution", 0)),
        evidence=[str(value) for value in item.get("evidence", [])],
    )
```

Modify `ArticleProcessResult(...)` construction:

```python
score_breakdown=[_score_breakdown_to_proto(part) for part in item.get("score_breakdown", [])],
recommendation_reasons=[str(value) for value in item.get("recommendation_reasons", [])],
rejection_reasons=[str(value) for value in item.get("rejection_reasons", [])],
rank_position=int(item.get("rank_position", 0)),
```

- [ ] **Step 7: Add protobuf service assertion**

In `AgentServiceTest.test_protobuf_service_process_articles`, add:

```python
self.assertEqual(response.results[0].rank_position, 1)
self.assertTrue(response.results[0].score_breakdown)
self.assertTrue(response.results[0].recommendation_reasons)
```

- [ ] **Step 8: Run proto and workflow tests**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
.\scripts\check_proto_contract.ps1
cd python-agent
python -m pytest tests/test_workflow.py -q
```

Expected: PASS.

## Task 5: Diversity Constraints

**Files:**
- Modify: `python-agent/app/recommendation/ranker.py`
- Modify: `python-agent/tests/test_recommendation_ranker.py`

- [ ] **Step 1: Write failing diversity test**

Append:

```python
class RecommendationDiversityTest(unittest.TestCase):
    def test_reranking_avoids_all_top_results_from_same_topic(self) -> None:
        settings = RecommendationSettings(min_keep_score=1.0)
        ranker = RecommendationRanker(settings)
        articles = [
            {"article_id": "ai-1", "title": "AI", "raw_text": "AI workflow" * 40, "source": "s1", "tags": ["ai"]},
            {"article_id": "ai-2", "title": "AI", "raw_text": "AI workflow" * 40, "source": "s1", "tags": ["ai"]},
            {"article_id": "ai-3", "title": "AI", "raw_text": "AI workflow" * 40, "source": "s1", "tags": ["ai"]},
            {"article_id": "db-1", "title": "Database", "raw_text": "database systems" * 40, "source": "s2", "tags": ["database"]},
        ]

        ranked = ranker.rank(articles, {"keywords": "AI,database"})
        top3_topics = [item.primary_topic for item in ranked[:3]]

        self.assertIn("database", top3_topics)
        self.assertLessEqual(max(top3_topics.count(topic) for topic in set(top3_topics)), 2)
```

- [ ] **Step 2: Run test to verify it fails if current simple diversity is insufficient**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_recommendation_ranker.py::RecommendationDiversityTest -q
```

Expected: FAIL if only consecutive-topic prevention is implemented.

- [ ] **Step 3: Implement window-aware diversity**

Update `_next_diverse_index` to score remaining items by topic/source scarcity:

```python
    def _next_diverse_index(self, selected: list[RankedArticle], remaining: list[RankedArticle]) -> int:
        window = selected[-self.settings.diversity.topic_window_size :]
        topic_counts = {item.primary_topic: sum(1 for prev in window if prev.primary_topic == item.primary_topic) for item in remaining}
        source_counts = {str(item.article.get("source", "")).lower(): sum(1 for prev in window if str(prev.article.get("source", "")).lower() == str(item.article.get("source", "")).lower()) for item in remaining}
        max_consecutive = self.settings.diversity.max_consecutive_same_topic
        recent = selected[-max_consecutive:]
        candidates: list[tuple[float, int]] = []
        for index, item in enumerate(remaining):
            if len(recent) == max_consecutive and all(prev.primary_topic == item.primary_topic for prev in recent):
                continue
            source = str(item.article.get("source", "")).lower()
            penalty = topic_counts.get(item.primary_topic, 0) + source_counts.get(source, 0) * 0.5
            candidates.append((penalty, index))
        if not candidates:
            return 0
        candidates.sort(key=lambda pair: (pair[0], -remaining[pair[1]].score, remaining[pair[1]].article_id))
        return candidates[0][1]
```

- [ ] **Step 4: Run ranker tests**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_recommendation_ranker.py -q
```

Expected: PASS.

## Task 6: Offline Evaluation Metrics and CLI

**Files:**
- Create: `python-agent/app/recommendation/evaluation.py`
- Create: `python-agent/scripts/evaluate_recommendations.py`
- Create: `python-agent/tests/test_recommendation_evaluation.py`

- [ ] **Step 1: Write failing metric tests**

Create `python-agent/tests/test_recommendation_evaluation.py`:

```python
import unittest

from app.recommendation.evaluation import evaluate_ranked_items


class RecommendationEvaluationTest(unittest.TestCase):
    def test_evaluation_metrics_at_k(self) -> None:
        ranked = [
            {"article_id": "a1", "label": 1, "relevance": 3, "topic": "ai", "url": "u1", "title": "t1"},
            {"article_id": "a2", "label": 0, "relevance": 0, "topic": "ai", "url": "u2", "title": "t2"},
            {"article_id": "a3", "label": 1, "relevance": 2, "topic": "db", "url": "u3", "title": "t3"},
        ]

        metrics = evaluate_ranked_items(ranked, k=2)

        self.assertEqual(metrics["k"], 2)
        self.assertEqual(metrics["items_evaluated"], 3)
        self.assertAlmostEqual(metrics["precision_at_k"], 0.5)
        self.assertAlmostEqual(metrics["recall_at_k"], 0.5)
        self.assertGreater(metrics["ndcg_at_k"], 0)
        self.assertAlmostEqual(metrics["diversity"], 0.5)
        self.assertAlmostEqual(metrics["duplicate_rate"], 0.0)

    def test_duplicate_rate_detects_repeated_url_title_or_id(self) -> None:
        ranked = [
            {"article_id": "a1", "label": 1, "relevance": 1, "topic": "ai", "url": "u1", "title": "same"},
            {"article_id": "a1", "label": 1, "relevance": 1, "topic": "ai", "url": "u2", "title": "same"},
        ]

        metrics = evaluate_ranked_items(ranked, k=2)

        self.assertGreater(metrics["duplicate_rate"], 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_recommendation_evaluation.py -q
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement evaluation functions**

Create `python-agent/app/recommendation/evaluation.py`:

```python
from __future__ import annotations

import math
from typing import Any


def evaluate_ranked_items(ranked: list[dict[str, Any]], k: int = 5) -> dict[str, float | int]:
    k = max(int(k), 1)
    top = ranked[:k]
    positives = sum(1 for item in ranked if int(item.get("label", 0)) > 0)
    hits = sum(1 for item in top if int(item.get("label", 0)) > 0)
    precision = hits / k
    recall = hits / positives if positives else 0.0
    dcg = _dcg([float(item.get("relevance", item.get("label", 0))) for item in top])
    ideal = sorted((float(item.get("relevance", item.get("label", 0))) for item in ranked), reverse=True)[:k]
    ideal_dcg = _dcg(ideal)
    topics = {str(item.get("topic") or item.get("primary_topic") or "unknown") for item in top}
    return {
        "k": k,
        "precision_at_k": round(precision, 6),
        "recall_at_k": round(recall, 6),
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
        values = [
            ("id", str(item.get("article_id", "")).strip().lower(), seen_ids),
            ("url", str(item.get("url", "")).strip().lower(), seen_urls),
            ("title", str(item.get("title", "")).strip().lower(), seen_titles),
        ]
        duplicated = False
        for _, value, seen in values:
            if not value:
                continue
            if value in seen:
                duplicated = True
            seen.add(value)
        if duplicated:
            duplicates += 1
    return duplicates / len(items) if items else 0.0
```

- [ ] **Step 4: Implement CLI**

Create `python-agent/scripts/evaluate_recommendations.py`:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from app.recommendation import RecommendationRanker, RecommendationSettings
from app.recommendation.evaluation import evaluate_ranked_items


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate offline recommendation ranking fixtures.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    payload = _read_payload(Path(args.input))
    ranker = RecommendationRanker(RecommendationSettings())
    ranked = ranker.rank(
        list(payload.get("articles", [])),
        dict(payload.get("user_profile_snapshot", {})),
        mcp_signals={str(item.get("article_id", "")): {"milvus_matches": item.get("milvus_matches"), "neo4j_topics": item.get("neo4j_topics")} for item in payload.get("articles", [])},
    )
    by_id = {str(item.get("article_id", "")): item for item in payload.get("articles", [])}
    metric_items = []
    for item in ranked:
        original = by_id.get(item.article_id, {})
        metric_items.append(
            {
                "article_id": item.article_id,
                "label": int(original.get("label", 0)),
                "relevance": float(original.get("relevance", original.get("label", 0))),
                "topic": item.primary_topic,
                "url": original.get("url", ""),
                "title": original.get("title", ""),
            }
        )
    report = evaluate_ranked_items(metric_items, k=args.k)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    return 0


def _read_payload(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return {"articles": [json.loads(line) for line in text.splitlines() if line.strip()]}
    return json.loads(text)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run evaluation tests**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_recommendation_evaluation.py -q
```

Expected: PASS.

## Task 7: Filter Skill and README Updates

**Files:**
- Modify: `python-agent/app/skills/filter_skill.md`
- Modify: `README.md`
- Test: `python-agent/tests/test_skills.py`

- [ ] **Step 1: Write failing documentation expectation if needed**

If `test_skills.py` remains section-only, no new failing test is required. Keep this task documentation-only and verify existing tests after editing.

- [ ] **Step 2: Update Filter skill output example**

Change score text in `python-agent/app/skills/filter_skill.md`:

```md
`score` 范围为 0 到 10。`score_breakdown` 必须包含每个评分维度的可用状态、归一化分、权重、贡献和证据。`keep=true` 通常要求 `score >= recommendation.min_keep_score`，并且文章不命中硬拒绝原因。
```

Update JSON examples to include:

```json
"rank_position": 1,
"score_breakdown": [
  {
    "dimension": "keyword_match",
    "available": true,
    "raw_score": 8.0,
    "normalized_score": 8.0,
    "weight": 1.0,
    "contribution": 8.0,
    "evidence": ["AI"]
  }
],
"recommendation_reasons": ["keyword_match 命中：AI"],
"rejection_reasons": []
```

- [ ] **Step 3: Update README**

Add a short section under Python Agent:

```md
### Recommendation Ranking

Filter Agent uses a configurable recommendation ranker. Scores are normalized to `0..10` and include `score_breakdown`, `recommendation_reasons`, `rejection_reasons`, and `rank_position` in gRPC responses.

Offline evaluation:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python scripts\evaluate_recommendations.py --input ..\shared\config\recommendation_eval.example.json --k 5
```
```

- [ ] **Step 4: Run skill test**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_skills.py -q
```

Expected: PASS.

## Task 8: Final Verification

**Files:**
- All modified files from previous tasks

- [ ] **Step 1: Run Python recommendation tests**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests/test_recommendation_ranker.py tests/test_recommendation_evaluation.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Python workflow tests**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m pytest tests -q
```

Expected: PASS.

- [ ] **Step 3: Run proto contract checks**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
.\scripts\check_proto_contract.ps1
```

Expected: PASS.

- [ ] **Step 4: Run Go tests**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\goframe-backend
go test ./... -count=1
```

Expected: PASS.

- [ ] **Step 5: Review git diff without staging unrelated files**

Run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
git status --short
git diff -- docs/superpowers/specs/2026-06-08-personalized-recommendation-ranking-design.md docs/superpowers/plans/2026-06-08-personalized-recommendation-ranking.md python-agent/app/recommendation python-agent/app/agents/filter_agent.py python-agent/app/config.py python-agent/app/workflow/graph.py python-agent/app/workflow/state.py python-agent/app/grpc_server.py python-agent/tests/test_recommendation_ranker.py python-agent/tests/test_recommendation_evaluation.py python-agent/tests/test_workflow.py python-agent/config.yaml python-agent/app/skills/filter_skill.md shared/proto/agent.proto proto/agent.proto goframe-backend/internal/agentpb/proto_contract_test.go scripts/check_proto_contract.ps1 README.md
```

Expected: Diff contains only recommendation ranking related changes. Do not use `git add .`; this repo already contains unrelated dirty changes.

## Self-Review

- Spec coverage: all requested scoring dimensions, configurable weights, `0..10` normalization, details, reasons, minimum keep score, source/topic diversity, no-Milvus/no-Neo4j degradation, deterministic ordering, and offline metrics are covered.
- Placeholder scan: no TBD/TODO/placeholder steps are present.
- Type consistency: plan uses `RecommendationSettings`, `RecommendationRanker`, `RankedArticle`, `score_breakdown`, `recommendation_reasons`, `rejection_reasons`, and `rank_position` consistently across Python, protobuf, and Go contract tests.
