from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "embedding-mcp"))
sys.path.insert(0, str(ROOT / "milvus-mcp"))
sys.path.insert(0, str(ROOT / "neo4j-mcp"))

from embedding_provider import OpenAIEmbeddingProvider  # noqa: E402
from milvus_store import MilvusVectorStore  # noqa: E402
from neo4j_store import Neo4jInterestGraphStore, normalize_interest_event  # noqa: E402


RUN_REAL = os.getenv("RUN_MEMORY_SERVICES_INTEGRATION", "").lower() in {"1", "true", "yes"}
RUN_OPENAI = os.getenv("RUN_OPENAI_EMBEDDING_SMOKE", "").lower() in {"1", "true", "yes"}


@unittest.skipUnless(RUN_REAL, "set RUN_MEMORY_SERVICES_INTEGRATION=1 to run Docker-backed integration tests")
class RealMemoryServicesIntegrationTest(unittest.TestCase):
    def test_milvus_crud_filter_and_deduplication(self) -> None:
        collection = f"user_memory_vectors_integration_{uuid4().hex[:8]}"
        store = MilvusVectorStore(
            uri=os.getenv("MILVUS_URI", "http://127.0.0.1:19530"),
            token=os.getenv("MILVUS_TOKEN", ""),
            collection_name=collection,
            dimension=3,
        )
        try:
            store.initialize()
            first = store.upsert(
                {
                    "embedding": [1, 0, 0],
                    "user_id": "integration-user",
                    "source": "integration",
                    "external_id": "one",
                    "topic": "AI",
                }
            )
            replay = store.upsert(
                {
                    "embedding": [1, 0, 0],
                    "user_id": "integration-user",
                    "source": "integration",
                    "external_id": "one",
                    "topic": "AI",
                }
            )
            matches = store.search(
                [1, 0, 0],
                limit=3,
                metadata_filter={"user_id": {"eq": "integration-user"}},
                minimum_score=0.99,
            )
            deduped = store.deduplicate(
                [{"id": "candidate", "embedding": [1, 0, 0], "user_id": "integration-user", "source": "integration"}],
                threshold=0.99,
                metadata_filter={"user_id": {"eq": "integration-user"}},
            )
            deleted = store.delete(ids=[str(first["id"])])

            self.assertEqual(first["id"], replay["id"])
            self.assertEqual(matches[0]["id"], first["id"])
            self.assertEqual(deduped["duplicate_groups"][0]["canonical_id"], first["id"])
            self.assertGreaterEqual(deleted["deleted_count"], 1)
        finally:
            if store.client is not None:
                store.client.drop_collection(collection)
            store.close()

    def test_neo4j_constraints_idempotent_update_and_explanation(self) -> None:
        store = Neo4jInterestGraphStore(
            uri=os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
            user=os.getenv("NEO4J_USER", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", "change-me-neo4j"),
            database=os.getenv("NEO4J_DATABASE", "neo4j"),
        )
        user_id = f"integration-{uuid4().hex}"
        event = normalize_interest_event(
            {"event_id": f"event-{uuid4().hex}", "user_id": user_id, "topics": [{"name": "AI", "weight": 0.8}]}
        )
        try:
            store.initialize()
            first = store.update_user_interests(event)
            replay = store.update_user_interests(event)
            topics = store.query_user_interests(user_id)
            explanation = store.explain_recommendation(user_id, {"topics": ["AI"], "title": "AI"})

            self.assertTrue(first["applied"])
            self.assertFalse(replay["applied"])
            self.assertEqual(topics[0]["weight"], 0.8)
            self.assertEqual(explanation["matched_topics"][0]["name"], "AI")
        finally:
            store.close()


@unittest.skipUnless(
    RUN_OPENAI and bool(os.getenv("OPENAI_API_KEY")),
    "set RUN_OPENAI_EMBEDDING_SMOKE=1 and OPENAI_API_KEY to run the paid OpenAI smoke test",
)
class RealOpenAIEmbeddingSmokeTest(unittest.TestCase):
    def test_real_openai_embedding(self) -> None:
        provider = OpenAIEmbeddingProvider(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-large"),
            dimension=int(os.getenv("EMBEDDING_DIMENSION", "3072")),
        )
        try:
            provider.initialize()
            result = provider.embed_text("KnowMate embedding smoke test")
            self.assertEqual(len(result["embedding"]), result["dim"])
            self.assertGreater(result["token_count"], 0)
        finally:
            provider.close()


if __name__ == "__main__":
    unittest.main()
