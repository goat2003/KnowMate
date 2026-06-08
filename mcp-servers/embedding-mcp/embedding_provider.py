from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import hashlib
import math
import re
import time
from typing import Any


JsonDict = dict[str, Any]


class EmbeddingProviderError(RuntimeError):
    pass


def _normalize_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text)).strip()
    if not normalized:
        raise EmbeddingProviderError("embedding text cannot be empty")
    return normalized


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        raise EmbeddingProviderError("embedding vector norm cannot be zero")
    return [value / norm for value in vector]


def _combine_vectors(vectors: list[list[float]], weights: list[int], dimension: int) -> list[float]:
    if not vectors:
        raise EmbeddingProviderError("embedding provider returned no vectors")
    total_weight = max(sum(weights), 1)
    combined = [0.0] * dimension
    for vector, weight in zip(vectors, weights, strict=True):
        if len(vector) != dimension:
            raise EmbeddingProviderError(
                f"embedding dimension mismatch: expected {dimension}, received {len(vector)}"
            )
        for index, value in enumerate(vector):
            combined[index] += float(value) * weight / total_weight
    return _l2_normalize(combined)


class MemoryEmbeddingProvider:
    def __init__(self, *, dimension: int = 8) -> None:
        self.dimension = max(int(dimension), 1)

    def initialize(self) -> None:
        return

    def close(self) -> None:
        return

    def health(self) -> JsonDict:
        return {"provider": "memory", "model": "mock-hash-embedding-v1", "dimension": self.dimension}

    def embed_text(self, text: str, options: JsonDict | None = None) -> JsonDict:
        started = time.perf_counter()
        normalized = _normalize_text(text)
        digest = hashlib.sha256(normalized.encode("utf-8")).digest()
        vector = [((digest[index % len(digest)] / 255.0) * 2) - 1 for index in range(self.dimension)]
        vector = _l2_normalize(vector)
        return {
            "embedding": vector,
            "dim": self.dimension,
            "model": "mock-hash-embedding-v1",
            "provider": "memory",
            "mock": True,
            "cache_hit": False,
            "token_count": max(len(normalized) // 4, 1),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "estimated_cost_usd": 0.0,
            "truncated": False,
            "chunk_count": 1,
        }

    def embed_batch(self, texts: list[str], options: JsonDict | None = None) -> JsonDict:
        items = [{"index": index, **self.embed_text(text, options)} for index, text in enumerate(texts)]
        return {
            "items": items,
            "embeddings": [item["embedding"] for item in items],
            "dim": self.dimension,
            "model": "mock-hash-embedding-v1",
            "provider": "memory",
            "mock": True,
            "token_count": sum(int(item["token_count"]) for item in items),
            "estimated_cost_usd": 0.0,
        }


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        *,
        client: object | None = None,
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        model: str = "text-embedding-3-large",
        dimension: int = 3072,
        timeout_seconds: float = 30,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.1,
        batch_size: int = 64,
        max_chars_per_chunk: int = 12000,
        max_chunks: int = 8,
        cache_size: int = 1024,
        cache_ttl_seconds: float = 3600,
        cost_per_million_tokens_usd: float | None = None,
    ) -> None:
        self.client = client
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimension = max(int(dimension), 1)
        self.timeout_seconds = max(float(timeout_seconds), 0.1)
        self.max_retries = max(int(max_retries), 0)
        self.retry_backoff_seconds = max(float(retry_backoff_seconds), 0)
        self.batch_size = max(int(batch_size), 1)
        self.max_chars_per_chunk = max(int(max_chars_per_chunk), 1)
        self.max_chunks = max(int(max_chunks), 1)
        self.cache_size = max(int(cache_size), 0)
        self.cache_ttl_seconds = max(float(cache_ttl_seconds), 0)
        self.cost_per_million_tokens_usd = cost_per_million_tokens_usd
        self._cache: OrderedDict[str, tuple[float, JsonDict]] = OrderedDict()

    def initialize(self) -> None:
        if self.client is not None:
            return
        if not self.api_key:
            raise EmbeddingProviderError("OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai")
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency is installed in production image
            raise EmbeddingProviderError("openai package is required for real embeddings") from exc
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            max_retries=0,
        )

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def health(self) -> JsonDict:
        return {
            "provider": "openai",
            "base_url": self.base_url,
            "model": self.model,
            "dimension": self.dimension,
            "client_ready": self.client is not None,
        }

    def embed_text(self, text: str, options: JsonDict | None = None) -> JsonDict:
        return self._embed_many([text])[0]

    def embed_batch(self, texts: list[str], options: JsonDict | None = None) -> JsonDict:
        items = [{"index": index, **item} for index, item in enumerate(self._embed_many(texts))]
        costs = [item["estimated_cost_usd"] for item in items if item["estimated_cost_usd"] is not None]
        return {
            "items": items,
            "embeddings": [item["embedding"] for item in items],
            "dim": self.dimension,
            "model": self.model,
            "provider": "openai",
            "mock": False,
            "token_count": sum(int(item["token_count"]) for item in items),
            "estimated_cost_usd": sum(float(cost) for cost in costs) if costs else None,
        }

    def _embed_many(self, texts: list[str]) -> list[JsonDict]:
        if not texts:
            return []
        self.initialize()
        started = time.perf_counter()
        normalized = [_normalize_text(text) for text in texts]
        results: list[JsonDict | None] = [None] * len(normalized)
        misses: list[tuple[int, str, list[str], bool]] = []
        for index, text in enumerate(normalized):
            cached = self._cache_get(self._cache_key(text))
            if cached is not None:
                cached["cache_hit"] = True
                cached["latency_ms"] = 0
                cached["estimated_cost_usd"] = 0.0
                results[index] = cached
                continue
            chunks, truncated = self._split_text(text)
            misses.append((index, text, chunks, truncated))

        flat_chunks = [chunk for _, _, chunks, _ in misses for chunk in chunks]
        flat_vectors: list[list[float]] = []
        total_tokens = 0
        for offset in range(0, len(flat_chunks), self.batch_size):
            vectors, tokens = self._request_batch(flat_chunks[offset : offset + self.batch_size])
            flat_vectors.extend(vectors)
            total_tokens += tokens

        estimated_weights = [max(len(chunk) // 4, 1) for chunk in flat_chunks]
        total_estimated = max(sum(estimated_weights), 1)
        cursor = 0
        for index, text, chunks, truncated in misses:
            count = len(chunks)
            vectors = flat_vectors[cursor : cursor + count]
            weights = estimated_weights[cursor : cursor + count]
            cursor += count
            token_count = round(total_tokens * sum(weights) / total_estimated) if total_tokens else sum(weights)
            item: JsonDict = {
                "embedding": _combine_vectors(vectors, weights, self.dimension),
                "dim": self.dimension,
                "model": self.model,
                "provider": "openai",
                "mock": False,
                "cache_hit": False,
                "token_count": token_count,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "estimated_cost_usd": self._cost(token_count),
                "truncated": truncated,
                "chunk_count": count,
            }
            self._cache_put(self._cache_key(text), item)
            results[index] = item
        return [result or {} for result in results]

    def _request_batch(self, texts: list[str]) -> tuple[list[list[float]], int]:
        if self.client is None:
            raise EmbeddingProviderError("OpenAI embedding client is unavailable")
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=texts,
                    dimensions=self.dimension,
                )
                data = sorted(response.data, key=lambda item: item.index)
                vectors = [[float(value) for value in item.embedding] for item in data]
                for vector in vectors:
                    if len(vector) != self.dimension:
                        raise EmbeddingProviderError(
                            f"embedding dimension mismatch: expected {self.dimension}, received {len(vector)}"
                        )
                usage = getattr(response, "usage", None)
                tokens = int(getattr(usage, "total_tokens", 0) or getattr(usage, "prompt_tokens", 0) or 0)
                return vectors, tokens
            except EmbeddingProviderError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries and self.retry_backoff_seconds:
                    time.sleep(self.retry_backoff_seconds * (2**attempt))
        raise EmbeddingProviderError(f"OpenAI embedding request failed: {last_error}") from last_error

    def _split_text(self, text: str) -> tuple[list[str], bool]:
        chunks = [
            text[offset : offset + self.max_chars_per_chunk]
            for offset in range(0, len(text), self.max_chars_per_chunk)
        ]
        truncated = len(chunks) > self.max_chunks
        return chunks[: self.max_chunks], truncated

    def _cache_key(self, text: str) -> str:
        identity = f"openai\0{self.base_url}\0{self.model}\0{self.dimension}\0{text}"
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> JsonDict | None:
        cached = self._cache.get(key)
        if cached is None:
            return None
        created_at, value = cached
        if self.cache_ttl_seconds and time.monotonic() - created_at > self.cache_ttl_seconds:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return deepcopy(value)

    def _cache_put(self, key: str, value: JsonDict) -> None:
        if not self.cache_size:
            return
        self._cache[key] = (time.monotonic(), deepcopy(value))
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)

    def _cost(self, token_count: int) -> float | None:
        if self.cost_per_million_tokens_usd is None:
            return None
        return token_count * float(self.cost_per_million_tokens_usd) / 1_000_000
