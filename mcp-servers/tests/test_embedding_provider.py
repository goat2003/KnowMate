from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import sys
import unittest


SERVER_DIR = Path(__file__).resolve().parents[1] / "embedding-mcp"
sys.path.insert(0, str(SERVER_DIR))

from embedding_provider import (  # noqa: E402
    EmbeddingProviderError,
    MemoryEmbeddingProvider,
    OpenAIEmbeddingProvider,
)


@dataclass
class FakeEmbedding:
    embedding: list[float]
    index: int


@dataclass
class FakeUsage:
    prompt_tokens: int
    total_tokens: int


@dataclass
class FakeResponse:
    data: list[FakeEmbedding]
    usage: FakeUsage


class FakeEmbeddings:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> FakeResponse:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome  # type: ignore[return-value]


class FakeClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.embeddings = FakeEmbeddings(outcomes)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def response(vectors: list[list[float]], tokens: int = 10) -> FakeResponse:
    return FakeResponse(
        data=[FakeEmbedding(vector, index) for index, vector in enumerate(vectors)],
        usage=FakeUsage(tokens, tokens),
    )


class EmbeddingProviderTest(unittest.TestCase):
    def test_memory_provider_is_deterministic_and_batches(self) -> None:
        provider = MemoryEmbeddingProvider(dimension=4)

        first = provider.embed_text("hello")
        second = provider.embed_text("hello")
        batch = provider.embed_batch(["hello", "world"])

        self.assertEqual(first["embedding"], second["embedding"])
        self.assertEqual(first["dim"], 4)
        self.assertEqual(len(batch["items"]), 2)
        self.assertEqual(batch["embeddings"][0], first["embedding"])

    def test_openai_provider_caches_and_records_usage_cost(self) -> None:
        client = FakeClient([response([[0.6, 0.8]], tokens=20)])
        provider = OpenAIEmbeddingProvider(
            client=client,
            dimension=2,
            cost_per_million_tokens_usd=2.5,
            cache_size=10,
            cache_ttl_seconds=60,
        )

        first = provider.embed_text("cached text")
        second = provider.embed_text("cached text")

        self.assertEqual(len(client.embeddings.calls), 1)
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(first["token_count"], 20)
        self.assertAlmostEqual(first["estimated_cost_usd"], 0.00005)
        self.assertEqual(second["estimated_cost_usd"], 0.0)

    def test_openai_provider_retries_transient_failure(self) -> None:
        client = FakeClient([TimeoutError("slow"), response([[1.0, 0.0]])])
        provider = OpenAIEmbeddingProvider(
            client=client,
            dimension=2,
            max_retries=1,
            retry_backoff_seconds=0,
        )

        result = provider.embed_text("retry me")

        self.assertEqual(result["embedding"], [1.0, 0.0])
        self.assertEqual(len(client.embeddings.calls), 2)

    def test_long_text_is_bounded_and_combined_to_normalized_vector(self) -> None:
        client = FakeClient([response([[1.0, 0.0], [0.0, 1.0]], tokens=8)])
        provider = OpenAIEmbeddingProvider(
            client=client,
            dimension=2,
            max_chars_per_chunk=5,
            max_chunks=2,
        )

        result = provider.embed_text("abcdefghijklmno")

        self.assertTrue(result["truncated"])
        self.assertEqual(result["chunk_count"], 2)
        vector = result["embedding"]
        self.assertAlmostEqual(math.sqrt(sum(value * value for value in vector)), 1.0)
        self.assertEqual(client.embeddings.calls[0]["input"], ["abcde", "fghij"])

    def test_provider_rejects_dimension_mismatch(self) -> None:
        provider = OpenAIEmbeddingProvider(client=FakeClient([response([[1.0, 0.0, 0.0]])]), dimension=2)

        with self.assertRaisesRegex(EmbeddingProviderError, "dimension"):
            provider.embed_text("wrong dimension")

    def test_missing_api_key_makes_real_provider_initialization_fail(self) -> None:
        provider = OpenAIEmbeddingProvider(api_key="", dimension=2)

        with self.assertRaisesRegex(EmbeddingProviderError, "OPENAI_API_KEY"):
            provider.initialize()


if __name__ == "__main__":
    unittest.main()
