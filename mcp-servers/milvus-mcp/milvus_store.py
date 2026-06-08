from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import time
from typing import Any


JsonDict = dict[str, Any]
ALLOWED_FILTER_FIELDS = {"id", "user_id", "source", "topic", "external_id", "content_hash", "created_at"}


class VectorStoreError(RuntimeError):
    pass


def stable_memory_id(user_id: str, source: str, external_id: str, content_hash: str) -> str:
    identity = f"{user_id}\0{source}\0{external_id or content_hash}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _content_hash(item: JsonDict, metadata: JsonDict) -> str:
    explicit = str(item.get("content_hash") or metadata.get("content_hash") or "").strip()
    if explicit:
        return explicit
    content = item.get("content", metadata.get("content", metadata.get("feedback", metadata)))
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_vector(vector: object, dimension: int) -> list[float]:
    if not isinstance(vector, list) or not vector or not all(isinstance(value, int | float) for value in vector):
        raise VectorStoreError("embedding must be a non-empty array of numbers")
    normalized = [float(value) for value in vector]
    if len(normalized) != dimension:
        raise VectorStoreError(f"embedding dimension mismatch: expected {dimension}, received {len(normalized)}")
    return normalized


def prepare_item(raw: JsonDict, dimension: int) -> JsonDict:
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        raise VectorStoreError("metadata must be an object")
    user_id = str(raw.get("user_id") or metadata.get("user_id") or "default-user").strip() or "default-user"
    source = str(raw.get("source") or metadata.get("source") or "memory").strip() or "memory"
    topic = str(raw.get("topic") or metadata.get("topic") or "").strip()
    external_id = str(raw.get("external_id") or metadata.get("external_id") or "").strip()
    content_hash = _content_hash(raw, metadata)
    memory_id = str(raw.get("id") or stable_memory_id(user_id, source, external_id, content_hash))
    return {
        "id": memory_id,
        "embedding": _validate_vector(raw.get("embedding"), dimension),
        "user_id": user_id,
        "source": source,
        "topic": topic,
        "external_id": external_id,
        "content_hash": content_hash,
        "created_at": int(raw.get("created_at") or time.time()),
        "metadata_json": deepcopy(metadata),
    }


def _escape_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _literal(value: object) -> str:
    if isinstance(value, str):
        return f"'{_escape_string(value)}'"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    raise VectorStoreError("metadata filter values must be strings, numbers, or booleans")


def compile_metadata_filter(metadata_filter: JsonDict | None) -> str:
    if not metadata_filter:
        return ""
    clauses: list[str] = []
    operators = {"eq": "=", "gte": ">=", "lte": "<="}
    for field, condition in metadata_filter.items():
        if field not in ALLOWED_FILTER_FIELDS:
            raise VectorStoreError(f"metadata filter field `{field}` is not allowed")
        if not isinstance(condition, dict) or len(condition) != 1:
            raise VectorStoreError(f"metadata filter for `{field}` must contain exactly one operator")
        operator, value = next(iter(condition.items()))
        if operator == "in":
            if not isinstance(value, list) or not value or len(value) > 100:
                raise VectorStoreError(f"metadata filter `in` for `{field}` must be a non-empty bounded array")
            clauses.append(f"{field} in [{', '.join(_literal(item) for item in value)}]")
        elif operator in operators:
            clauses.append(f"{field} {operators[operator]} {_literal(value)}")
        else:
            raise VectorStoreError(f"metadata filter operator `{operator}` is not allowed")
    return " and ".join(clauses)


def _matches_filter(item: JsonDict, metadata_filter: JsonDict | None) -> bool:
    if not metadata_filter:
        return True
    for field, condition in metadata_filter.items():
        if field not in ALLOWED_FILTER_FIELDS or not isinstance(condition, dict) or len(condition) != 1:
            compile_metadata_filter(metadata_filter)
        operator, expected = next(iter(condition.items()))
        actual = item.get(field)
        if operator == "eq" and actual != expected:
            return False
        if operator == "in" and actual not in expected:
            return False
        if operator == "gte" and (actual is None or actual < expected):
            return False
        if operator == "lte" and (actual is None or actual > expected):
            return False
    return True


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


class MemoryVectorStore:
    def __init__(self, *, dimension: int = 8, collection_name: str = "user_memory_vectors") -> None:
        self.dimension = max(int(dimension), 1)
        self.collection_name = collection_name
        self.items: dict[str, JsonDict] = {}

    def initialize(self) -> None:
        return

    def close(self) -> None:
        return

    def health(self) -> JsonDict:
        return {
            "provider": "memory",
            "collection": self.collection_name,
            "dimension": self.dimension,
            "count": len(self.items),
        }

    def upsert(self, item: JsonDict) -> JsonDict:
        prepared = prepare_item(item, self.dimension)
        self.items[str(prepared["id"])] = prepared
        return {"upserted": True, "id": prepared["id"], "count": len(self.items), "mock": True}

    def upsert_batch(self, items: list[JsonDict]) -> JsonDict:
        prepared = [prepare_item(item, self.dimension) for item in items]
        for item in prepared:
            self.items[str(item["id"])] = item
        return {"upserted_count": len(prepared), "ids": [item["id"] for item in prepared], "mock": True}

    def search(
        self,
        vector: list[float],
        *,
        limit: int = 3,
        metadata_filter: JsonDict | None = None,
        minimum_score: float | None = None,
    ) -> list[JsonDict]:
        query = _validate_vector(vector, self.dimension)
        compile_metadata_filter(metadata_filter)
        matches = []
        for item in self.items.values():
            if not _matches_filter(item, metadata_filter):
                continue
            score = _cosine(query, item["embedding"])
            if minimum_score is not None and score < minimum_score:
                continue
            matches.append(
                {
                    "id": item["id"],
                    "score": round(score, 6),
                    "metadata": deepcopy(item["metadata_json"]),
                    "user_id": item["user_id"],
                    "source": item["source"],
                    "topic": item["topic"],
                }
            )
        matches.sort(key=lambda item: item["score"], reverse=True)
        return matches[: max(1, min(int(limit), 100))]

    def delete(self, *, ids: list[str] | None = None, metadata_filter: JsonDict | None = None) -> JsonDict:
        ids = [str(value) for value in ids or [] if str(value)]
        if not ids and not metadata_filter:
            raise VectorStoreError("unqualified delete is not allowed")
        compile_metadata_filter(metadata_filter)
        targets = {
            item_id
            for item_id, item in self.items.items()
            if (item_id in ids) or (metadata_filter is not None and _matches_filter(item, metadata_filter))
        }
        for item_id in targets:
            del self.items[item_id]
        return {"deleted_count": len(targets), "ids": sorted(targets), "mock": True}

    def deduplicate(
        self,
        items: list[JsonDict],
        *,
        threshold: float = 0.88,
        metadata_filter: JsonDict | None = None,
    ) -> JsonDict:
        prepared = [prepare_item(item, self.dimension) for item in items]
        unique: list[JsonDict] = []
        duplicate_groups: list[JsonDict] = []
        existing = [item for item in self.items.values() if _matches_filter(item, metadata_filter)]
        for item in prepared:
            candidates = existing + unique
            best = max(
                ((candidate, _cosine(item["embedding"], candidate["embedding"])) for candidate in candidates),
                key=lambda pair: pair[1],
                default=(None, -1.0),
            )
            if best[0] is not None and best[1] >= threshold:
                duplicate_groups.append(
                    {"canonical_id": best[0]["id"], "duplicate_id": item["id"], "score": round(best[1], 6)}
                )
            else:
                unique.append(item)
        return {
            "unique_items": [item["id"] for item in unique],
            "duplicate_groups": duplicate_groups,
            "threshold": threshold,
            "mock": True,
        }


class MilvusVectorStore:
    REQUIRED_FIELDS = {"id", "embedding", "user_id", "source", "topic", "external_id", "content_hash", "created_at", "metadata_json"}

    def __init__(
        self,
        *,
        client: object | None = None,
        uri: str = "http://127.0.0.1:19530",
        token: str = "",
        collection_name: str = "user_memory_vectors",
        dimension: int = 3072,
        timeout_seconds: float = 10,
    ) -> None:
        self.client = client
        self.uri = uri
        self.token = token
        self.collection_name = collection_name
        self.dimension = max(int(dimension), 1)
        self.timeout_seconds = max(float(timeout_seconds), 0.1)

    def initialize(self) -> None:
        if self.client is None:
            try:
                from pymilvus import MilvusClient
            except ImportError as exc:  # pragma: no cover - installed in production image
                raise VectorStoreError("pymilvus package is required for real Milvus mode") from exc
            self.client = MilvusClient(uri=self.uri, token=self.token, timeout=self.timeout_seconds)
        if not self.client.has_collection(self.collection_name, timeout=self.timeout_seconds):
            self._create_collection()
        else:
            self._validate_collection(self.client.describe_collection(self.collection_name, timeout=self.timeout_seconds))
            self._validate_indexes()
        self.client.load_collection(self.collection_name, timeout=self.timeout_seconds)

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def health(self) -> JsonDict:
        collections = self.client.list_collections(timeout=self.timeout_seconds) if self.client is not None else []
        return {
            "provider": "milvus",
            "uri": self.uri,
            "collection": self.collection_name,
            "dimension": self.dimension,
            "collection_present": self.collection_name in collections,
        }

    def upsert(self, item: JsonDict) -> JsonDict:
        return self.upsert_batch([item]) | {"id": prepare_item(item, self.dimension)["id"], "upserted": True}

    def upsert_batch(self, items: list[JsonDict]) -> JsonDict:
        prepared = [prepare_item(item, self.dimension) for item in items]
        result = self.client.upsert(
            collection_name=self.collection_name,
            data=prepared,
            timeout=self.timeout_seconds,
        )
        return {"upserted_count": len(prepared), "ids": [item["id"] for item in prepared], "result": result, "mock": False}

    def search(
        self,
        vector: list[float],
        *,
        limit: int = 3,
        metadata_filter: JsonDict | None = None,
        minimum_score: float | None = None,
    ) -> list[JsonDict]:
        query = _validate_vector(vector, self.dimension)
        results = self.client.search(
            collection_name=self.collection_name,
            data=[query],
            filter=compile_metadata_filter(metadata_filter),
            limit=max(1, min(int(limit), 100)),
            output_fields=list(self.REQUIRED_FIELDS - {"embedding"}),
            search_params={"metric_type": "COSINE", "params": {"ef": 64}},
            timeout=self.timeout_seconds,
        )
        matches: list[JsonDict] = []
        for hit in results[0] if results else []:
            score = float(hit.get("distance", hit.get("score", 0.0)))
            if minimum_score is not None and score < minimum_score:
                continue
            entity = hit.get("entity", {})
            matches.append(
                {
                    "id": str(hit.get("id", entity.get("id", ""))),
                    "score": round(score, 6),
                    "metadata": entity.get("metadata_json", {}),
                    "user_id": entity.get("user_id", ""),
                    "source": entity.get("source", ""),
                    "topic": entity.get("topic", ""),
                }
            )
        return matches

    def delete(self, *, ids: list[str] | None = None, metadata_filter: JsonDict | None = None) -> JsonDict:
        ids = [str(value) for value in ids or [] if str(value)]
        if not ids and not metadata_filter:
            raise VectorStoreError("unqualified delete is not allowed")
        result = self.client.delete(
            collection_name=self.collection_name,
            ids=ids or None,
            filter=compile_metadata_filter(metadata_filter) or None,
            timeout=self.timeout_seconds,
        )
        return {"deleted_count": int(result.get("delete_count", 0)), "ids": ids, "mock": False}

    def deduplicate(
        self,
        items: list[JsonDict],
        *,
        threshold: float = 0.88,
        metadata_filter: JsonDict | None = None,
    ) -> JsonDict:
        prepared = [prepare_item(item, self.dimension) for item in items]
        unique: list[JsonDict] = []
        duplicates: list[JsonDict] = []
        for item in prepared:
            existing = self.search(item["embedding"], limit=1, metadata_filter=metadata_filter, minimum_score=threshold)
            batch_candidates = [
                (candidate, _cosine(item["embedding"], candidate["embedding"])) for candidate in unique
            ]
            best_batch = max(batch_candidates, key=lambda pair: pair[1], default=(None, -1.0))
            if existing:
                duplicates.append(
                    {"canonical_id": existing[0]["id"], "duplicate_id": item["id"], "score": existing[0]["score"]}
                )
            elif best_batch[0] is not None and best_batch[1] >= threshold:
                duplicates.append(
                    {"canonical_id": best_batch[0]["id"], "duplicate_id": item["id"], "score": round(best_batch[1], 6)}
                )
            else:
                unique.append(item)
        return {
            "unique_items": [item["id"] for item in unique],
            "duplicate_groups": duplicates,
            "threshold": threshold,
            "mock": False,
        }

    def _create_collection(self) -> None:
        data_types = _data_types()
        schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(field_name="id", datatype=data_types["VARCHAR"], is_primary=True, max_length=64)
        schema.add_field(field_name="embedding", datatype=data_types["FLOAT_VECTOR"], dim=self.dimension)
        for field in ["user_id", "source", "topic", "external_id", "content_hash"]:
            schema.add_field(field_name=field, datatype=data_types["VARCHAR"], max_length=512)
        schema.add_field(field_name="created_at", datatype=data_types["INT64"])
        schema.add_field(field_name="metadata_json", datatype=data_types["JSON"])
        indexes = self.client.prepare_index_params()
        indexes.add_index(
            field_name="embedding",
            index_name="embedding_hnsw",
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 16, "efConstruction": 200},
        )
        self.client.create_collection(collection_name=self.collection_name, schema=schema, index_params=indexes)

    def _validate_collection(self, description: JsonDict) -> None:
        fields = {str(field.get("name")): field for field in description.get("fields", [])}
        embedding = fields.get("embedding")
        if embedding is None:
            raise VectorStoreError("Milvus collection is incompatible: missing embedding field")
        params = embedding.get("params", {}) if isinstance(embedding.get("params", {}), dict) else {}
        actual_dimension = int(params.get("dim", embedding.get("dim", 0)) or 0)
        if actual_dimension != self.dimension:
            raise VectorStoreError(
                f"Milvus collection dimension mismatch: expected {self.dimension}, received {actual_dimension}"
            )
        missing = sorted(self.REQUIRED_FIELDS - set(fields))
        if missing:
            raise VectorStoreError(f"Milvus collection is incompatible: missing fields {', '.join(missing)}")
        if not bool(fields["id"].get("is_primary")):
            raise VectorStoreError("Milvus collection is incompatible: id must be the primary field")
        expected_types = {
            "id": "VARCHAR",
            "embedding": "FLOAT_VECTOR",
            "user_id": "VARCHAR",
            "source": "VARCHAR",
            "topic": "VARCHAR",
            "external_id": "VARCHAR",
            "content_hash": "VARCHAR",
            "created_at": "INT64",
            "metadata_json": "JSON",
        }
        for name, expected in expected_types.items():
            actual = _type_name(fields[name].get("type"))
            if expected not in actual:
                raise VectorStoreError(
                    f"Milvus collection is incompatible: field `{name}` type must be {expected}, received {actual}"
                )

    def _validate_indexes(self) -> None:
        if not hasattr(self.client, "list_indexes") or not hasattr(self.client, "describe_index"):
            return
        indexes = self.client.list_indexes(self.collection_name, field_name="embedding")
        if not indexes:
            raise VectorStoreError("Milvus collection is incompatible: missing embedding index")
        description = self.client.describe_index(
            self.collection_name,
            index_name=str(indexes[0]),
            timeout=self.timeout_seconds,
        )
        metric = str(description.get("metric_type", "")).upper()
        index_type = str(description.get("index_type", "")).upper()
        if metric and metric != "COSINE":
            raise VectorStoreError(f"Milvus collection metric mismatch: expected COSINE, received {metric}")
        if index_type and index_type != "HNSW":
            raise VectorStoreError(f"Milvus collection index mismatch: expected HNSW, received {index_type}")


def _data_types() -> dict[str, object]:
    try:
        from pymilvus import DataType

        return {
            "VARCHAR": DataType.VARCHAR,
            "FLOAT_VECTOR": DataType.FLOAT_VECTOR,
            "INT64": DataType.INT64,
            "JSON": DataType.JSON,
        }
    except ImportError:
        return {"VARCHAR": "VARCHAR", "FLOAT_VECTOR": "FLOAT_VECTOR", "INT64": "INT64", "JSON": "JSON"}


def _type_name(value: object) -> str:
    name = getattr(value, "name", None)
    return str(name or value).upper()
