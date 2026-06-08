from __future__ import annotations

from pathlib import Path
import sys
import unittest


SERVER_DIR = Path(__file__).resolve().parents[1] / "neo4j-mcp"
sys.path.insert(0, str(SERVER_DIR))

from neo4j_store import (  # noqa: E402
    MemoryInterestGraphStore,
    Neo4jInterestGraphStore,
    normalize_interest_event,
    stable_event_id,
)


class FakeDriver:
    def __init__(self, results: list[object] | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.verified = False
        self.closed = False

    def verify_connectivity(self) -> None:
        self.verified = True

    def execute_query(self, query: str, **kwargs: object) -> object:
        self.calls.append((query, kwargs))
        if self.results:
            return self.results.pop(0)
        return []

    def close(self) -> None:
        self.closed = True


class Neo4jStoreTest(unittest.TestCase):
    def test_stable_event_id_is_repeatable(self) -> None:
        payload = {"user_id": "u1", "topics": [{"name": "AI", "weight": 0.2}], "sentiment": "positive"}

        first = stable_event_id(payload)
        second = stable_event_id(dict(payload))

        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_memory_update_is_idempotent_for_same_event(self) -> None:
        store = MemoryInterestGraphStore()
        event = normalize_interest_event(
            {"event_id": "evt-1", "user_id": "u1", "topics": [{"name": "AI", "weight": 0.2}]}
        )

        first = store.update_user_interests(event)
        second = store.update_user_interests(event)

        self.assertTrue(first["applied"])
        self.assertFalse(second["applied"])
        self.assertEqual(store.query_user_interests("u1")[0]["weight"], 0.2)

    def test_memory_query_and_explanation_are_graph_derived(self) -> None:
        store = MemoryInterestGraphStore()
        store.update_user_interests(
            normalize_interest_event(
                {"event_id": "evt-ai", "user_id": "u1", "topics": [{"name": "AI", "weight": 0.8}]}
            )
        )

        explanation = store.explain_recommendation("u1", {"title": "AI workflow", "topics": ["AI"]})

        self.assertEqual(explanation["matched_topics"][0]["name"], "AI")
        self.assertEqual(explanation["score"], 0.8)
        self.assertIn("AI", explanation["reasons"][0])

    def test_real_store_initializes_constraints_and_indexes(self) -> None:
        driver = FakeDriver()
        store = Neo4jInterestGraphStore(driver=driver)

        store.initialize()

        self.assertTrue(driver.verified)
        statements = "\n".join(query for query, _ in driver.calls)
        self.assertIn("CREATE CONSTRAINT", statements)
        self.assertIn("CREATE INDEX", statements)
        self.assertTrue(all("IF NOT EXISTS" in query for query, _ in driver.calls))

    def test_real_update_uses_fixed_parameterized_cypher(self) -> None:
        driver = FakeDriver(results=[[{"applied": True}]])
        store = Neo4jInterestGraphStore(driver=driver)
        event = normalize_interest_event(
            {"event_id": "evt-1", "user_id": "user-injection", "topics": [{"name": "AI", "weight": 0.2}]}
        )

        result = store.update_user_interests(event)

        query, kwargs = driver.calls[0]
        self.assertNotIn("user-injection", query)
        self.assertNotIn("evt-1", query)
        self.assertIn("$user_id", query)
        self.assertEqual(kwargs["parameters_"]["user_id"], "user-injection")
        self.assertTrue(result["applied"])

    def test_real_interest_query_returns_ranked_records(self) -> None:
        driver = FakeDriver(results=[[{"name": "AI", "weight": 0.9}, {"name": "DB", "weight": 0.4}]])
        store = Neo4jInterestGraphStore(driver=driver)

        topics = store.query_user_interests("u1", limit=2)

        self.assertEqual([topic["name"] for topic in topics], ["AI", "DB"])
        self.assertNotIn("u1", driver.calls[0][0])
        self.assertEqual(driver.calls[0][1]["parameters_"]["user_id"], "u1")


if __name__ == "__main__":
    unittest.main()
