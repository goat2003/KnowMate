"""Semantic entity grounding for relation retrieval."""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.common.manager.neo4j_manager import Neo4jManager
from app.DBserver.milvus_repository.milvus_operate import MilvusCRUD
from app.retrieval.milvus_search import first_hit_page, quote_expr_value, search_raw_hits
from app.retrieval.models import clamp_score
from app.retrieval.score import cosine_to_score, lexical_overlap_score, parse_time_value
from app.retrieval.utils import clean_text_list, escape_lucene_fulltext_query, fulltext_index_exists, hit_entity

logger = logging.getLogger(__name__)


TYPE_PRIORITY = {
    "person": 1.0,
    "user": 1.0,
    "organization": 0.9,
    "location": 0.85,
    "project": 0.82,
    "technology": 0.8,
    "Entity": 0.8,
}
ENTITY_SCORE_WEIGHTS = {
    "name_match_score": 0.50,
    "retrieval_score": 0.40,
    "type_priority_score": 0.07,
    "recency_score": 0.03,
}


class SemanticEntityRetriever:
    def __init__(
        self,
        manager: Optional[Neo4jManager] = None,
        milvus_crud: Optional[MilvusCRUD] = None,
        milvus_manager: Optional[Any] = None,
        embedding_client: Optional[Any] = None,
    ):
        self.manager = manager or Neo4jManager.get_instance()
        self.milvus_crud = milvus_crud or milvus_manager or MilvusCRUD()
        self.embedding_client = embedding_client

    async def ground(
        self,
        role_id: str,
        query_text: str,
        query_entities: List[str],
        current_time: Any = None,
        top_per_entity: int = 3,
        max_entities: int = 10,
    ) -> List[Dict[str, Any]]:
        grounded: List[Dict[str, Any]] = []
        for query_entity in clean_text_list(query_entities):
            rows: List[Dict[str, Any]] = []
            rows.extend(await self._exact_match(role_id, query_text, query_entity, current_time))
            rows.extend(await self._fulltext_match(role_id, query_text, query_entity, current_time))
            rows.extend(await self._vector_match(role_id, query_text, query_entity, current_time))

            by_uuid: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                uuid = row.get("uuid")
                if not uuid:
                    continue
                existing = by_uuid.get(uuid)
                if existing is None:
                    row["retrieval_sources"] = clean_text_list(row.get("retrieval_sources") or [])
                    by_uuid[uuid] = row
                    continue
                if row.get("entity_score", 0.0) > existing.get("entity_score", 0.0):
                    row["retrieval_sources"] = clean_text_list(
                        [*(existing.get("retrieval_sources") or []), *(row.get("retrieval_sources") or [])]
                    )
                    by_uuid[uuid] = row
                else:
                    existing["retrieval_sources"] = clean_text_list(
                        [*(existing.get("retrieval_sources") or []), *(row.get("retrieval_sources") or [])]
                    )

            grounded.extend(
                sorted(by_uuid.values(), key=lambda item: item.get("entity_score", 0.0), reverse=True)[:top_per_entity]
            )

        deduped: Dict[str, Dict[str, Any]] = {}
        for row in grounded:
            uuid = row.get("uuid")
            if not uuid:
                continue
            existing = deduped.get(uuid)
            if existing is None or row.get("entity_score", 0.0) > existing.get("entity_score", 0.0):
                if existing:
                    row["retrieval_sources"] = clean_text_list(
                        [*(existing.get("retrieval_sources") or []), *(row.get("retrieval_sources") or [])]
                    )
                deduped[uuid] = row
            else:
                existing["retrieval_sources"] = clean_text_list(
                    [*(existing.get("retrieval_sources") or []), *(row.get("retrieval_sources") or [])]
                )

        return sorted(deduped.values(), key=lambda item: item.get("entity_score", 0.0), reverse=True)[:max_entities]

    async def hydrate(self, role_id: str, entity_uuids: List[str]) -> Dict[str, Dict[str, Any]]:
        if not entity_uuids:
            return {}
        query = """
        MATCH (n:Entity {role_id: $role_id})
        WHERE n.entity_uuid IN $entity_uuids
        RETURN
            n.entity_uuid AS uuid,
            n.role_id AS role_id,
            labels(n) AS labels,
            n.name AS name,
            n.type AS type,
            n.semantic AS semantic,
            null AS created_at,
            null AS last_accessed_at
        """
        rows = await self.manager.execute_query(query, {"role_id": role_id, "entity_uuids": entity_uuids})
        return {row.get("uuid"): self._normalize_row(row) for row in rows if row.get("uuid")}

    async def _exact_match(
        self,
        role_id: str,
        query_text: str,
        query_entity: str,
        current_time: Any,
    ) -> List[Dict[str, Any]]:
        query = """
        MATCH (n:Entity {role_id: $role_id})
        WHERE n.name = $query_entity
        RETURN
            n.entity_uuid AS uuid,
            n.role_id AS role_id,
            labels(n) AS labels,
            n.name AS name,
            n.type AS type,
            n.semantic AS semantic,
            null AS created_at,
            null AS last_accessed_at,
            1.0 AS raw_score
        LIMIT 5
        """
        rows = await self.manager.execute_query(
            query,
            {"role_id": role_id, "query_entity": query_entity},
        )
        return [
            self._score_row(row, query_text, query_entity, 1.0, current_time, ["exact"])
            for row in rows
        ]

    async def _fulltext_match(
        self,
        role_id: str,
        query_text: str,
        query_entity: str,
        current_time: Any,
    ) -> List[Dict[str, Any]]:
        fulltext_query = escape_lucene_fulltext_query(query_entity)
        if not fulltext_query:
            return []
        if not await fulltext_index_exists(self.manager, "entity_fulltext"):
            rows = await self._contains_match_raw(role_id, query_entity)
            raw_max = max([float(row.get("raw_score") or 0.0) for row in rows] or [0.0])
            return [
                self._score_row(
                    row,
                    query_text,
                    query_entity,
                    float(row.get("raw_score") or 0.0) / raw_max if raw_max > 0 else 0.65,
                    current_time,
                    ["contains"],
                )
                for row in rows
            ]
        query = """
        CALL db.index.fulltext.queryNodes("entity_fulltext", $query_entity)
        YIELD node, score
        WHERE node:Entity AND node.role_id = $role_id
        RETURN
            node.entity_uuid AS uuid,
            node.role_id AS role_id,
            labels(node) AS labels,
            node.name AS name,
            node.type AS type,
            node.semantic AS semantic,
            null AS created_at,
            null AS last_accessed_at,
            score AS raw_score
        LIMIT 10
        """
        try:
            rows = await self.manager.execute_query(
                query,
                {"role_id": role_id, "query_entity": fulltext_query},
            )
        except Exception as exc:
            logger.warning("Semantic entity fulltext failed, fallback to contains: %s", exc)
            rows = await self._contains_match_raw(role_id, query_entity)

        raw_max = max([float(row.get("raw_score") or 0.0) for row in rows] or [0.0])
        result = []
        for row in rows:
            raw = float(row.get("raw_score") or 0.0)
            retrieval_score = raw / raw_max if raw_max > 0 else 0.65
            result.append(self._score_row(row, query_text, query_entity, retrieval_score, current_time, ["fulltext"]))
        return result

    async def _contains_match_raw(self, role_id: str, query_entity: str) -> List[Dict[str, Any]]:
        query = """
        MATCH (n:Entity {role_id: $role_id})
        WHERE n.name CONTAINS $query_entity OR $query_entity CONTAINS n.name
        RETURN
            n.entity_uuid AS uuid,
            n.role_id AS role_id,
            labels(n) AS labels,
            n.name AS name,
            n.type AS type,
            n.semantic AS semantic,
            null AS created_at,
            null AS last_accessed_at,
            0.65 AS raw_score
        LIMIT 10
        """
        return await self.manager.execute_query(query, {"role_id": role_id, "query_entity": query_entity})

    async def _vector_match(
        self,
        role_id: str,
        query_text: str,
        query_entity: str,
        current_time: Any,
    ) -> List[Dict[str, Any]]:
        try:
            embedding = await self._embed(query_entity)
        except Exception as exc:
            logger.warning("Semantic entity embedding failed, skip vector grounding: %s", exc)
            return []
        if not embedding:
            return []

        loop = asyncio.get_running_loop()
        vector_rows: List[Dict[str, Any]] = []
        try:
            raw = await loop.run_in_executor(
                None,
                lambda: search_raw_hits(
                    self.milvus_crud,
                    collection_name="SemanticEntity",
                    embedding=embedding,
                    vector_field="semantic_embedding",
                    top_k=5,
                    expr=f"role_id == {quote_expr_value(role_id)}",
                ),
            )
        except Exception as exc:
            logger.warning("Semantic entity vector search failed: %s", exc)
            return []

        for hit in first_hit_page(raw):
            entity = hit_entity(hit)
            vector_rows.append(
                {
                    "uuid": entity.get("uuid"),
                    "role_id": entity.get("role_id") or role_id,
                    "labels": ["Entity"],
                    "name": entity.get("name", ""),
                    "type": entity.get("type", ""),
                    "semantic": entity.get("semantic", ""),
                    "created_at": None,
                    "last_accessed_at": None,
                    "raw_score": getattr(hit, "distance", None),
                    "vector_score": cosine_to_score(getattr(hit, "distance", None)),
                }
            )

        hydrated = await self.hydrate(role_id, [row["uuid"] for row in vector_rows if row.get("uuid")])
        result = []
        for row in vector_rows:
            if row.get("uuid") in hydrated:
                row.update(hydrated[row["uuid"]])
            retrieval_score = row.get("vector_score", 0.0)
            result.append(self._score_row(row, query_text, query_entity, retrieval_score, current_time, ["vector"]))
        return result

    async def _embed(self, text: str) -> List[float]:
        if self.embedding_client is None:
            from app.common.client.embedding_client import get_embedding_client

            client = get_embedding_client()
        else:
            client = self.embedding_client
        return await client.embed(text)

    def _score_row(
        self,
        row: Dict[str, Any],
        query_text: str,
        query_entity: str,
        retrieval_score: float,
        current_time: Any,
        sources: List[str],
    ) -> Dict[str, Any]:
        normalized = self._normalize_row(row)
        name_match_score = self._name_match_score(query_text, query_entity, normalized.get("name", ""))
        retrieval_score = clamp_score(retrieval_score)
        type_priority_score = TYPE_PRIORITY.get(str(normalized.get("type") or "").lower(), TYPE_PRIORITY["Entity"])
        recency_score = self._recency_score(normalized.get("last_accessed_at") or normalized.get("created_at"), current_time)
        normalized.update(
            {
                "query_entity": query_entity,
                "name_match_score": name_match_score,
                "retrieval_score": retrieval_score,
                "type_priority_score": type_priority_score,
                "recency_score": recency_score,
                "entity_score": clamp_score(
                    name_match_score * ENTITY_SCORE_WEIGHTS["name_match_score"]
                    + retrieval_score * ENTITY_SCORE_WEIGHTS["retrieval_score"]
                    + type_priority_score * ENTITY_SCORE_WEIGHTS["type_priority_score"]
                    + recency_score * ENTITY_SCORE_WEIGHTS["recency_score"]
                ),
                "retrieval_sources": clean_text_list(sources),
            }
        )
        return normalized

    @staticmethod
    def _normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "uuid": row.get("uuid"),
            "role_id": row.get("role_id"),
            "label": "Entity",
            "labels": list(row.get("labels") or ["Entity"]),
            "name": row.get("name") or "",
            "type": row.get("type") or "",
            "semantic": row.get("semantic") or "",
            "created_at": row.get("created_at"),
            "last_accessed_at": row.get("last_accessed_at"),
        }

    @staticmethod
    def _name_match_score(query_text: str, query_entity: str, entity_name: str) -> float:
        query = str(query_text or "").lower()
        expected = str(query_entity or "").lower()
        name = str(entity_name or "").lower()
        if not name:
            return 0.0
        if name == expected:
            return 1.0
        if name in query:
            return 0.95
        if expected and (expected in name or name in expected):
            return 0.75
        return lexical_overlap_score(query_entity, entity_name)

    @staticmethod
    def _recency_score(value: Any, current_time: Any) -> float:
        timestamp = parse_time_value(value)
        now = parse_time_value(current_time) or datetime.now(timezone.utc)
        if timestamp is None:
            return 0.5
        age_days = max((now - timestamp).days, 0)
        return clamp_score(1.0 / (1.0 + math.log1p(age_days) / 5.0))
