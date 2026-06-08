import unittest
from datetime import datetime, timezone

from app.config import Settings
from app.recommendation import RecommendationRanker, RecommendationSettings


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

    def test_ranker_keeps_valid_article_when_milvus_and_neo4j_are_unavailable(self) -> None:
        ranker = RecommendationRanker(RecommendationSettings())

        results = ranker.rank(
            [
                {
                    "article_id": "fallback",
                    "url": "https://example.com/fallback",
                    "title": "AI workflow",
                    "raw_text": "Short but valid article text about AI workflow.",
                    "source": "rss",
                }
            ],
            {"interests": "AI"},
            now=datetime(2026, 6, 8, tzinfo=timezone.utc),
        )

        item = results[0]
        self.assertTrue(item.keep)
        self.assertGreaterEqual(item.score, RecommendationSettings().min_keep_score)


class RecommendationDiversityTest(unittest.TestCase):
    def test_reranking_avoids_all_top_results_from_same_topic(self) -> None:
        settings = RecommendationSettings(min_keep_score=1.0)
        ranker = RecommendationRanker(settings)
        articles = [
            {"article_id": "ai-1", "title": "AI", "raw_text": "AI workflow " * 40, "source": "s1", "tags": ["ai"]},
            {"article_id": "ai-2", "title": "AI", "raw_text": "AI workflow " * 40, "source": "s1", "tags": ["ai"]},
            {"article_id": "ai-3", "title": "AI", "raw_text": "AI workflow " * 40, "source": "s1", "tags": ["ai"]},
            {"article_id": "db-1", "title": "Database", "raw_text": "database systems " * 40, "source": "s2", "tags": ["database"]},
        ]

        ranked = ranker.rank(articles, {"keywords": "AI,database"})
        top3_topics = [item.primary_topic for item in ranked[:3]]

        self.assertIn("database", top3_topics)
        self.assertLessEqual(max(top3_topics.count(topic) for topic in set(top3_topics)), 2)

    def test_reranking_respects_source_and_topic_ratio_limits(self) -> None:
        settings = RecommendationSettings(min_keep_score=1.0)
        settings.diversity.max_same_source_ratio = 0.5
        settings.diversity.max_same_topic_ratio = 0.5
        ranker = RecommendationRanker(settings)
        articles = [
            {"article_id": "ai-1", "title": "AI", "raw_text": "AI workflow " * 40, "source": "s1", "tags": ["ai"]},
            {"article_id": "ai-2", "title": "AI", "raw_text": "AI workflow " * 40, "source": "s1", "tags": ["ai"]},
            {"article_id": "ai-3", "title": "AI", "raw_text": "AI workflow " * 40, "source": "s1", "tags": ["ai"]},
            {"article_id": "ai-4", "title": "AI", "raw_text": "AI workflow " * 40, "source": "s1", "tags": ["ai"]},
            {"article_id": "db-1", "title": "Database", "raw_text": "database systems " * 40, "source": "s2", "tags": ["database"]},
            {"article_id": "ml-1", "title": "Machine learning", "raw_text": "machine learning systems " * 40, "source": "s3", "tags": ["ml"]},
        ]

        ranked = ranker.rank(articles, {"keywords": "AI,database,machine"})
        top4 = ranked[:4]
        top4_sources = [str(item.article.get("source", "")).lower() for item in top4]
        top4_topics = [item.primary_topic for item in top4]

        self.assertLessEqual(top4_sources.count("s1"), 2)
        self.assertLessEqual(top4_topics.count("ai"), 2)


if __name__ == "__main__":
    unittest.main()
