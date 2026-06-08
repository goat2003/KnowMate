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


if __name__ == "__main__":
    unittest.main()
