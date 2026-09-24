"""Retrieve propertyless Entity ``RELATES_TO`` evidence from production graph data."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, MutableMapping, Optional, Tuple

from app.common.manager.neo4j_manager import Neo4jManager
from app.DBserver.milvus_repository.milvus_operate import MilvusCRUD
from app.retrieval.fact_source_provider import CONTENT_ORIGIN, OriginalFactSourceProvider, get_many_for_role
from app.retrieval.models import EvidenceItem, clamp_score
from app.retrieval.score import (
    SEMANTIC_EDGE_SCORE_WEIGHTS,
    SEMANTIC_PATH_SCORE_WEIGHTS,
    compute_edge_quality_score,
    compute_hop_score,
    compute_relation_source_score,
    compute_semantic_edge_score,
    compute_semantic_path_score,
    compute_time_score,
    lexical_overlap_score,
    normalize_scores,
    score_formula,
)
from app.retrieval.semantic_entity_retriever import SemanticEntityRetriever
from app.retrieval.trace import record as trace_record
from app.retrieval.trace import row as trace_row
from app.retrieval.utils import clean_text_list, escape_lucene_fulltext_query

logger = logging.getLogger(__name__)


class EntityRelationRetriever:
    """Retrieve relation evidence without depending on RELATES_TO properties.

    Production writes bare ``RELATES_TO`` relationships.  Every fact binding in
    this retriever is consequently recovered through a ChunkNode shared by the
    two relation endpoints and the matched OriginalFact.
    """

    _EVIDENCE_FIELDS = (
        "ori_fact_uuid",
        "fact_summary",
        "fact_confidence",
        "fact_importance",
        "fact_create_time",
        "fact_last_update_time",
        "chunk_uuid",
        "chunk_valid_time",
        "chunk_create_time",
    )

    def __init__(
        self,
        manager: Optional[Neo4jManager] = None,
        milvus_crud: Optional[MilvusCRUD] = None,
        milvus_manager: Optional[Any] = None,
        embedding_client: Optional[Any] = None,
        semantic_entity_retriever: Optional[SemanticEntityRetriever] = None,
        source_provider: Optional[Any] = None,
    ):
        self.manager = manager or Neo4jManager.get_instance()
        # Keep this dependency for SemanticEntityRetriever compatibility.  This
        # retriever deliberately performs no relation-vector search.
        self.milvus_crud = milvus_crud or milvus_manager or MilvusCRUD()
        self.embedding_client = embedding_client
        self.source_provider = source_provider or OriginalFactSourceProvider()
        self.semantic_entity_retriever = semantic_entity_retriever or SemanticEntityRetriever(
            manager=self.manager,
            milvus_crud=self.milvus_crud,
            embedding_client=embedding_client,
        )

    async def retrieve(
        self,
        role_id: str,
        sub_query: Dict[str, Any],
        query_embedding: Optional[List[float]] = None,
        current_time: Any = None,
        top_k: int = 10,
        trace: Optional[MutableMapping[str, Any]] = None,
    ) -> List[EvidenceItem]:
        query_text = str(sub_query.get("query") or "").strip()
        query_entities = clean_text_list(sub_query.get("entities") or [])
        time_constraint = sub_query.get("time") or {}
        max_hops = self._max_hops(sub_query)

        entity_rows = await self.semantic_entity_retriever.ground(
            role_id=role_id,
            query_text=query_text,
            query_entities=query_entities,
            current_time=current_time,
            top_per_entity=5,
            max_entities=16,
        )
        entity_score_map = {
            row["uuid"]: row.get("entity_score", 0.0)
            for row in entity_rows
            if row.get("uuid")
        }
        entity_uuids = list(entity_score_map)
        candidate_pool_size = max(top_k * 6, 30)

        edge_candidates: Dict[str, Dict[str, Any]] = {}
        if entity_uuids:
            graph_rows = await self._graph_edge_search(role_id, entity_uuids, candidate_pool_size)
            for raw_rank, row in enumerate(graph_rows, start=1):
                row.setdefault("raw_hit_rank", raw_rank)
                trace_record(trace, "raw_hits", trace_row(row, source="relation"))
                self._merge_edge_candidate(edge_candidates, row, "graph", row.get("edge_retrieval_score", 0.82))

        # Fulltext uses OriginalFact.summary and still runs when entity grounding
        # yields nothing, so relation recall is not gated on entity recognition.
        fulltext_rows = await self._edge_fulltext_search(role_id, query_text, candidate_pool_size)
        for raw_rank, row in enumerate(fulltext_rows, start=1):
            row.setdefault("raw_hit_rank", raw_rank)
            trace_record(trace, "raw_hits", trace_row(row, source="relation"))
            self._merge_edge_candidate(edge_candidates, row, "fulltext", row.get("edge_retrieval_score", 0.0))

        await self._attach_edge_evidence_from_shared_chunks(role_id, edge_candidates)
        await self._hydrate_edge_source_content(role_id, edge_candidates.values())

        items: List[EvidenceItem] = []
        for row in edge_candidates.values():
            trace_record(trace, "has_fact_bindings", trace_row(row, source="relation"))
            item = self._edge_to_evidence(
                row=row,
                query_text=query_text,
                query_entities=query_entities,
                entity_score_map=entity_score_map,
                time_constraint=time_constraint,
            )
            if item:
                items.append(item)
                trace_record(trace, "route_candidates", trace_row({
                    "chunk_uuid": item.chunk_uuid,
                    "ori_fact_uuid": item.ori_fact_uuid,
                    "fact_uuid": item.fact_uuid,
                    "valid_time": item.valid_time,
                    "local_score": item.local_score,
                }, source=item.source))

        if entity_uuids and self._should_expand_paths(sub_query, entity_uuids, edge_candidates, items, max_hops):
            path_rows = await self._two_hop_path_search(role_id, entity_uuids, top_k=max(40, top_k * 4))
            for row in path_rows:
                trace_record(trace, "raw_hits", trace_row(row, source="relation"))
            await self._attach_path_evidence_from_shared_chunks(role_id, path_rows)
            await self._hydrate_path_source_content(role_id, path_rows)
            for row in path_rows:
                trace_record(trace, "has_fact_bindings", trace_row(row, source="relation"))
                item = self._path_to_evidence(
                    row=row,
                    query_text=query_text,
                    query_entities=query_entities,
                    entity_score_map=entity_score_map,
                    time_constraint=time_constraint,
                )
                if item:
                    items.append(item)
                    trace_record(trace, "route_candidates", trace_row({
                        "chunk_uuid": item.chunk_uuid,
                        "ori_fact_uuid": item.ori_fact_uuid,
                        "fact_uuid": item.fact_uuid,
                        "valid_time": item.valid_time,
                        "local_score": item.local_score,
                    }, source=item.source))

        items = [item for item in items if item and item.content]
        if not items and query_entities:
            items = await self._legacy_entity_fact_fallback(
                role_id=role_id,
                query_text=query_text,
                query_entities=query_entities,
                top_k=top_k,
            )
            for item in items:
                trace_record(trace, "has_fact_bindings", trace_row({
                    "chunk_uuid": item.chunk_uuid,
                    "ori_fact_uuid": item.ori_fact_uuid,
                    "fact_uuid": item.fact_uuid,
                    "valid_time": item.valid_time,
                    "local_score": item.local_score,
                }, source=item.source))
                trace_record(trace, "route_candidates", trace_row({
                    "chunk_uuid": item.chunk_uuid,
                    "ori_fact_uuid": item.ori_fact_uuid,
                    "fact_uuid": item.fact_uuid,
                    "valid_time": item.valid_time,
                    "local_score": item.local_score,
                }, source=item.source))
        return sorted(items, key=lambda item: item.local_score, reverse=True)[:top_k]

    @staticmethod
    def _max_hops(sub_query: Dict[str, Any]) -> int:
        try:
            value = int(sub_query.get("max_hops") or 1)
        except (TypeError, ValueError):
            value = 1
        if str(sub_query.get("relation_intent") or "") == "path":
            value = max(value, 2)
        return max(1, min(value, 3))

    async def _graph_edge_search(self, role_id: str, entity_uuids: List[str], top_k: int) -> List[Dict[str, Any]]:
        query = """
        MATCH (source:Entity {role_id: $role_id})-[relation:RELATES_TO]-(target:Entity {role_id: $role_id})
        WHERE source.entity_uuid IN $entity_uuids OR target.entity_uuid IN $entity_uuids
        RETURN
            CASE WHEN source.entity_uuid IN $entity_uuids THEN source.entity_uuid ELSE target.entity_uuid END AS matched_entity_uuid,
            source.entity_uuid AS source_uuid,
            labels(source) AS source_labels,
            source.name AS source_name,
            source.type AS source_type,
            source.semantic AS source_semantic,
            target.entity_uuid AS target_uuid,
            labels(target) AS target_labels,
            target.name AS target_name,
            target.type AS target_type,
            target.semantic AS target_semantic,
            type(relation) AS relation_label,
            0.82 AS edge_retrieval_score
        LIMIT $limit
        """
        return await self.manager.execute_query(
            query,
            {"role_id": role_id, "entity_uuids": entity_uuids, "limit": int(top_k)},
        )

    async def _edge_fulltext_search(self, role_id: str, query_text: str, top_k: int) -> List[Dict[str, Any]]:
        if not query_text:
            return []
        fulltext_query = escape_lucene_fulltext_query(query_text)
        if not fulltext_query:
            return []
        query = """
        CALL db.index.fulltext.queryNodes($index_name, $query_text)
        YIELD node AS original, score
        WHERE original:OriginalFact AND original.role_id = $role_id
        MATCH (chunk:ChunkNode {role_id: $role_id})-[:HAS_FACT]->(original)
        MATCH (chunk)-[:HAS_ENTITY]->(source:Entity {role_id: $role_id})-[relation:RELATES_TO]-(target:Entity {role_id: $role_id})
        MATCH (chunk)-[:HAS_ENTITY]->(target)
        WHERE source.entity_uuid <> target.entity_uuid
        RETURN
            source.entity_uuid AS source_uuid,
            labels(source) AS source_labels,
            source.name AS source_name,
            source.type AS source_type,
            source.semantic AS source_semantic,
            target.entity_uuid AS target_uuid,
            labels(target) AS target_labels,
            target.name AS target_name,
            target.type AS target_type,
            target.semantic AS target_semantic,
            type(relation) AS relation_label,
            original.ori_fact_uuid AS ori_fact_uuid,
            original.summary AS fact_summary,
            original.confidence AS fact_confidence,
            original.importance AS fact_importance,
            original.create_time AS fact_create_time,
            original.last_update_time AS fact_last_update_time,
            chunk.chunk_uuid AS chunk_uuid,
            chunk.valid_time AS chunk_valid_time,
            chunk.create_time AS chunk_create_time,
            score AS edge_retrieval_score
        LIMIT $limit
        """
        rows: List[Dict[str, Any]] = []
        try:
            rows = await self.manager.execute_query(
                query,
                {
                    "index_name": "original_fact_summary_fulltext",
                    "role_id": role_id,
                    "query_text": fulltext_query,
                    "limit": int(top_k),
                },
            )
        except Exception as exc:
            logger.warning("OriginalFact relation fulltext failed, fallback to summary contains: %s", exc)

        # Empty fulltext results are also a fallback condition.  The fallback is
        # intentionally anchored on OriginalFact.summary, never relation data.
        if not rows:
            rows = await self._edge_contains_search(role_id, query_text, top_k)
        for row in rows:
            row["evidence_origin"] = row.get("evidence_origin") or "original_fact_summary_match"
        normalize_scores(rows, "edge_retrieval_score")
        return rows

    async def _edge_contains_search(self, role_id: str, query_text: str, top_k: int) -> List[Dict[str, Any]]:
        keywords = [token for token in clean_text_list([query_text, *query_text.split()]) if len(token) >= 2][:8]
        if not keywords:
            return []
        query = """
        MATCH (original:OriginalFact {role_id: $role_id})
        WHERE ANY(keyword IN $keywords WHERE original.summary CONTAINS keyword)
        MATCH (chunk:ChunkNode {role_id: $role_id})-[:HAS_FACT]->(original)
        MATCH (chunk)-[:HAS_ENTITY]->(source:Entity {role_id: $role_id})-[relation:RELATES_TO]-(target:Entity {role_id: $role_id})
        MATCH (chunk)-[:HAS_ENTITY]->(target)
        WHERE source.entity_uuid <> target.entity_uuid
        RETURN
            source.entity_uuid AS source_uuid,
            labels(source) AS source_labels,
            source.name AS source_name,
            source.type AS source_type,
            source.semantic AS source_semantic,
            target.entity_uuid AS target_uuid,
            labels(target) AS target_labels,
            target.name AS target_name,
            target.type AS target_type,
            target.semantic AS target_semantic,
            type(relation) AS relation_label,
            original.ori_fact_uuid AS ori_fact_uuid,
            original.summary AS fact_summary,
            original.confidence AS fact_confidence,
            original.importance AS fact_importance,
            original.create_time AS fact_create_time,
            original.last_update_time AS fact_last_update_time,
            chunk.chunk_uuid AS chunk_uuid,
            chunk.valid_time AS chunk_valid_time,
            chunk.create_time AS chunk_create_time,
            0.70 AS edge_retrieval_score
        LIMIT $limit
        """
        rows = await self.manager.execute_query(
            query,
            {"role_id": role_id, "keywords": keywords, "limit": int(top_k)},
        )
        for row in rows:
            row["evidence_origin"] = row.get("evidence_origin") or "original_fact_summary_contains"
        return rows

    async def _attach_edge_evidence_from_shared_chunks(
        self,
        role_id: str,
        candidates: Dict[str, Dict[str, Any]],
    ) -> None:
        evidence_by_pair = await self._load_relation_evidence(role_id, self._edge_pairs(candidates.values()))
        for row in candidates.values():
            evidence = evidence_by_pair.get(self._relation_pair_key(row.get("source_uuid"), row.get("target_uuid")))
            self._copy_evidence_if_missing(row, evidence)

    async def _attach_path_evidence_from_shared_chunks(self, role_id: str, rows: List[Dict[str, Any]]) -> None:
        pairs: List[Tuple[Any, Any]] = []
        for row in rows:
            pairs.extend(((row.get("start_uuid"), row.get("mid_uuid")), (row.get("mid_uuid"), row.get("finish_uuid"))))
        evidence_by_pair = await self._load_relation_evidence(role_id, pairs)
        for row in rows:
            for prefix, source_key, target_key in (
                ("r1", "start_uuid", "mid_uuid"),
                ("r2", "mid_uuid", "finish_uuid"),
            ):
                evidence = evidence_by_pair.get(
                    self._relation_pair_key(row.get(source_key), row.get(target_key))
                )
                if not evidence:
                    continue
                for field in self._EVIDENCE_FIELDS:
                    value = evidence.get(field)
                    if value not in (None, ""):
                        row[f"{prefix}_{field}"] = value
                row[f"{prefix}_evidence_origin"] = evidence.get("evidence_origin")

    async def _load_relation_evidence(
        self,
        role_id: str,
        edge_pairs: List[Tuple[Any, Any]],
    ) -> Dict[Tuple[str, str], Dict[str, Any]]:
        clean_pairs = []
        seen = set()
        for source_uuid, target_uuid in edge_pairs:
            key = self._relation_pair_key(source_uuid, target_uuid)
            if not key or key in seen:
                continue
            seen.add(key)
            clean_pairs.append({"source_uuid": key[0], "target_uuid": key[1]})
        if not clean_pairs:
            return {}

        query = """
        UNWIND $edge_pairs AS pair
        MATCH (source:Entity {role_id: $role_id})-[relation:RELATES_TO]-(target:Entity {role_id: $role_id})
        WHERE (source.entity_uuid = pair.source_uuid AND target.entity_uuid = pair.target_uuid)
           OR (source.entity_uuid = pair.target_uuid AND target.entity_uuid = pair.source_uuid)
        MATCH (chunk:ChunkNode {role_id: $role_id})-[:HAS_ENTITY]->(source)
        MATCH (chunk)-[:HAS_ENTITY]->(target)
        MATCH (chunk)-[:HAS_FACT]->(original:OriginalFact {role_id: $role_id})
        WITH pair, source, target, chunk, original
        ORDER BY pair.source_uuid, pair.target_uuid, original.importance DESC, original.last_update_time DESC
        WITH pair, collect({
            source_uuid: source.entity_uuid,
            target_uuid: target.entity_uuid,
            ori_fact_uuid: original.ori_fact_uuid,
            fact_summary: original.summary,
            fact_confidence: original.confidence,
            fact_importance: original.importance,
            fact_create_time: original.create_time,
            fact_last_update_time: original.last_update_time,
            chunk_uuid: chunk.chunk_uuid,
            chunk_valid_time: chunk.valid_time,
            chunk_create_time: chunk.create_time
        })[0] AS evidence
        RETURN
            evidence.source_uuid AS source_uuid,
            evidence.target_uuid AS target_uuid,
            evidence.ori_fact_uuid AS ori_fact_uuid,
            evidence.fact_summary AS fact_summary,
            evidence.fact_confidence AS fact_confidence,
            evidence.fact_importance AS fact_importance,
            evidence.fact_create_time AS fact_create_time,
            evidence.fact_last_update_time AS fact_last_update_time,
            evidence.chunk_uuid AS chunk_uuid,
            evidence.chunk_valid_time AS chunk_valid_time,
            evidence.chunk_create_time AS chunk_create_time
        """
        try:
            rows = await self.manager.execute_query(
                query,
                {"role_id": role_id, "edge_pairs": clean_pairs},
            )
        except Exception as exc:
            logger.warning("Shared ChunkNode relation evidence lookup failed: %s", exc)
            return {}

        result: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for row in rows or []:
            key = self._relation_pair_key(row.get("source_uuid"), row.get("target_uuid"))
            if key and key not in result and row.get("ori_fact_uuid"):
                copied = dict(row)
                copied["evidence_origin"] = "shared_chunk_original_fact"
                result[key] = copied
        return result

    @classmethod
    def _copy_evidence_if_missing(cls, row: Dict[str, Any], evidence: Optional[Dict[str, Any]]) -> None:
        if not evidence:
            return
        for field in cls._EVIDENCE_FIELDS:
            if row.get(field) in (None, "") and evidence.get(field) not in (None, ""):
                row[field] = evidence[field]
        if not row.get("evidence_origin"):
            row["evidence_origin"] = evidence.get("evidence_origin")

    async def _hydrate_edge_source_content(self, role_id: str, rows: Any) -> None:
        rows = list(rows or [])
        ori_fact_uuids = list(
            dict.fromkeys(str(row["ori_fact_uuid"]) for row in rows if row.get("ori_fact_uuid"))
        )
        if not ori_fact_uuids:
            return
        contents = await get_many_for_role(self.source_provider, ori_fact_uuids, role_id)
        for row in rows:
            ori_fact_uuid = row.get("ori_fact_uuid")
            if ori_fact_uuid:
                row["evidence_content"] = contents.get(str(ori_fact_uuid), "")
                row["content_origin"] = CONTENT_ORIGIN

    async def _hydrate_path_source_content(self, role_id: str, rows: Any) -> None:
        rows = list(rows or [])
        ori_fact_uuids = list(
            dict.fromkeys(
                str(row.get(f"{prefix}_ori_fact_uuid"))
                for row in rows
                for prefix in ("r1", "r2")
                if row.get(f"{prefix}_ori_fact_uuid")
            )
        )
        if not ori_fact_uuids:
            return
        contents = await get_many_for_role(self.source_provider, ori_fact_uuids, role_id)
        for row in rows:
            for prefix in ("r1", "r2"):
                ori_fact_uuid = row.get(f"{prefix}_ori_fact_uuid")
                if ori_fact_uuid:
                    row[f"{prefix}_evidence_content"] = contents.get(str(ori_fact_uuid), "")
                    row[f"{prefix}_content_origin"] = CONTENT_ORIGIN

    async def _two_hop_path_search(self, role_id: str, entity_uuids: List[str], top_k: int) -> List[Dict[str, Any]]:
        query = """
        MATCH (start:Entity {role_id: $role_id})-[r1:RELATES_TO]-(mid:Entity {role_id: $role_id})-[r2:RELATES_TO]-(finish:Entity {role_id: $role_id})
        WHERE start.entity_uuid IN $entity_uuids
          AND finish.entity_uuid IN $entity_uuids
          AND start.entity_uuid <> finish.entity_uuid
        RETURN
            start.entity_uuid AS start_uuid,
            labels(start) AS start_labels,
            start.name AS start_name,
            start.type AS start_type,
            start.semantic AS start_semantic,
            mid.entity_uuid AS mid_uuid,
            labels(mid) AS mid_labels,
            mid.name AS mid_name,
            mid.type AS mid_type,
            mid.semantic AS mid_semantic,
            finish.entity_uuid AS finish_uuid,
            labels(finish) AS finish_labels,
            finish.name AS finish_name,
            finish.type AS finish_type,
            finish.semantic AS finish_semantic,
            type(r1) AS r1_relation,
            type(r2) AS r2_relation
        LIMIT $limit
        """
        rows = await self.manager.execute_query(
            query,
            {"role_id": role_id, "entity_uuids": entity_uuids, "limit": int(top_k * 2)},
        )
        deduped: Dict[Tuple[str, ...], Dict[str, Any]] = {}
        per_start_count: Dict[str, int] = {}
        for row in rows:
            start_uuid = row.get("start_uuid")
            if per_start_count.get(start_uuid, 0) >= 5:
                continue
            row["r1_uuid"] = self._synthetic_relation_uuid(row.get("start_uuid"), row.get("mid_uuid"))
            row["r2_uuid"] = self._synthetic_relation_uuid(row.get("mid_uuid"), row.get("finish_uuid"))
            key = tuple(sorted((str(row["r1_uuid"]), str(row["r2_uuid"]))))
            endpoint_key = tuple(sorted((str(row.get("start_uuid")), str(row.get("finish_uuid")))))
            canonical = (*key, *endpoint_key)
            if canonical in deduped:
                continue
            deduped[canonical] = row
            per_start_count[start_uuid] = per_start_count.get(start_uuid, 0) + 1
            if len(deduped) >= 30:
                break
        return list(deduped.values())

    def _merge_edge_candidate(
        self,
        candidates: Dict[str, Dict[str, Any]],
        row: Dict[str, Any],
        source: str,
        retrieval_score: Any,
    ) -> None:
        relation_uuid = self._synthetic_relation_uuid(row.get("source_uuid"), row.get("target_uuid"))
        if not relation_uuid:
            return
        row["relation_uuid"] = relation_uuid
        retrieval_score = clamp_score(retrieval_score)
        if relation_uuid not in candidates:
            row["edge_retrieval_sources"] = [source]
            row["edge_retrieval_score"] = retrieval_score
            candidates[relation_uuid] = row
            return

        existing = candidates[relation_uuid]
        existing["edge_retrieval_sources"] = clean_text_list(
            [*(existing.get("edge_retrieval_sources") or []), source]
        )
        existing["edge_retrieval_score"] = clamp_score(
            max(existing.get("edge_retrieval_score", 0.0), retrieval_score) + 0.05
        )
        if row.get("matched_entity_uuid") and not existing.get("matched_entity_uuid"):
            existing["matched_entity_uuid"] = row.get("matched_entity_uuid")
        # A fulltext candidate has a fact/chunk binding that is more precise
        # than graph expansion.  Never replace a populated binding with an
        # unrelated shared-chunk fact.
        self._copy_evidence_if_missing(existing, row)
        if row.get("evidence_origin") and existing.get("ori_fact_uuid") == row.get("ori_fact_uuid"):
            existing["evidence_origin"] = row["evidence_origin"]

    @staticmethod
    def _synthetic_relation_uuid(source_uuid: Any, target_uuid: Any) -> Optional[str]:
        if not source_uuid or not target_uuid:
            return None
        left, right = sorted((str(source_uuid), str(target_uuid)))
        return f"rel:{left}:{right}"

    @staticmethod
    def _synthetic_path_key(*uuids: Any) -> Optional[str]:
        values = [str(value) for value in uuids if value]
        if len(values) < 3:
            return None
        return "path:" + ":".join(values)

    @staticmethod
    def _relation_pair_key(source_uuid: Any, target_uuid: Any) -> Optional[Tuple[str, str]]:
        if not source_uuid or not target_uuid:
            return None
        return tuple(sorted((str(source_uuid), str(target_uuid))))

    @classmethod
    def _edge_pairs(cls, rows: Any) -> List[Tuple[Any, Any]]:
        return [(row.get("source_uuid"), row.get("target_uuid")) for row in rows or []]

    def _edge_to_evidence(
        self,
        row: Dict[str, Any],
        query_text: str,
        query_entities: List[str],
        entity_score_map: Dict[str, float],
        time_constraint: Dict[str, Any],
    ) -> Optional[EvidenceItem]:
        content = self._edge_content(row)
        if not content:
            return None
        start_entity_score = self._endpoint_score(
            row.get("source_uuid"), row.get("source_name"), entity_score_map, query_text, query_entities
        )
        end_entity_score = self._endpoint_score(
            row.get("target_uuid"), row.get("target_name"), entity_score_map, query_text, query_entities
        )
        edge_retrieval_score = clamp_score(row.get("edge_retrieval_score", 0.0))
        fact_relevance_score = lexical_overlap_score(" ".join([query_text, *query_entities]), content)
        edge_quality_score = compute_edge_quality_score(
            True,
            content,
            row.get("ori_fact_uuid"),
            row.get("chunk_uuid"),
            row.get("fact_confidence"),
            row.get("fact_importance"),
        )
        time_score = compute_time_score(
            time_constraint,
            row.get("chunk_valid_time"),
        )
        local_score = compute_semantic_edge_score(
            start_entity_score=start_entity_score,
            end_entity_score=end_entity_score,
            edge_retrieval_score=edge_retrieval_score,
            fact_relevance_score=fact_relevance_score,
            edge_quality_score=edge_quality_score,
            time_score=time_score,
        )
        components = {
            "start_entity_score": start_entity_score,
            "end_entity_score": end_entity_score,
            "edge_retrieval_score": edge_retrieval_score,
            "fact_relevance_score": fact_relevance_score,
            "edge_quality_score": edge_quality_score,
            "time_score": time_score,
        }
        return EvidenceItem(
            source="relation",
            evidence_type="semantic_fact_edge",
            content=content,
            local_score=local_score,
            path=self._edge_path(row),
            entity_uuid=row.get("source_uuid"),
            ori_fact_uuid=row.get("ori_fact_uuid") or None,
            fact_uuid=row.get("ori_fact_uuid") or None,
            chunk_uuid=row.get("chunk_uuid") or None,
            valid_time=row.get("chunk_valid_time"),
            create_time=row.get("fact_create_time") or row.get("fact_last_update_time") or row.get("chunk_create_time"),
            metadata={
                "relation_uuid": row.get("relation_uuid"),
                "start_entity": row.get("source_name"),
                "start_entity_uuid": row.get("source_uuid"),
                "target_entity": row.get("target_name"),
                "target_entity_uuid": row.get("target_uuid"),
                "relation": row.get("relation_label"),
                "evidence_origin": row.get("evidence_origin"),
                "content_origin": row.get("content_origin"),
                "edge_retrieval_sources": clean_text_list(row.get("edge_retrieval_sources") or []),
                "raw_hit_rank": row.get("raw_hit_rank"),
                "route_raw_hit_ranks": {"relation": row.get("raw_hit_rank")},
                "route_retrieval_scores": {"relation": row.get("edge_retrieval_score")},
                "evidence": self._evidence_metadata(row),
                "path_hops": 1,
                "score_formula": score_formula("edge_score", SEMANTIC_EDGE_SCORE_WEIGHTS),
                "score_components": components,
                **components,
            },
        )

    def _path_to_evidence(
        self,
        row: Dict[str, Any],
        query_text: str,
        query_entities: List[str],
        entity_score_map: Dict[str, float],
        time_constraint: Dict[str, Any],
    ) -> Optional[EvidenceItem]:
        content = self._two_hop_content(row)
        if not content:
            return None
        r1_uuid = row.get("r1_uuid") or self._synthetic_relation_uuid(row.get("start_uuid"), row.get("mid_uuid"))
        r2_uuid = row.get("r2_uuid") or self._synthetic_relation_uuid(row.get("mid_uuid"), row.get("finish_uuid"))
        start_entity_score = self._endpoint_score(
            row.get("start_uuid"), row.get("start_name"), entity_score_map, query_text, query_entities
        )
        path_relevance_score = lexical_overlap_score(" ".join([query_text, *query_entities]), content)
        edge_quality_1 = self._path_edge_quality(row, "r1")
        edge_quality_2 = self._path_edge_quality(row, "r2")
        edge_quality_score = clamp_score((edge_quality_1 + edge_quality_2) / 2.0)
        source_score = max(
            compute_relation_source_score(row.get("r1_ori_fact_uuid"), row.get("r1_chunk_uuid")),
            compute_relation_source_score(row.get("r2_ori_fact_uuid"), row.get("r2_chunk_uuid")),
        )
        time_score = max(self._path_time_score(row, "r1", time_constraint), self._path_time_score(row, "r2", time_constraint))
        components = {
            "start_entity_score": start_entity_score,
            "path_relevance_score": path_relevance_score,
            "hop_score": compute_hop_score(2),
            "edge_quality_score": edge_quality_score,
            "source_score": source_score,
            "time_score": time_score,
        }
        return EvidenceItem(
            source="relation",
            evidence_type="semantic_fact_path",
            content=content,
            local_score=compute_semantic_path_score(**components),
            path=self._two_hop_path(row),
            entity_uuid=row.get("start_uuid"),
            ori_fact_uuid=row.get("r1_ori_fact_uuid") or row.get("r2_ori_fact_uuid") or None,
            fact_uuid=row.get("r1_ori_fact_uuid") or row.get("r2_ori_fact_uuid") or None,
            chunk_uuid=row.get("r1_chunk_uuid") or row.get("r2_chunk_uuid") or None,
            valid_time=row.get("r1_chunk_valid_time") or row.get("r2_chunk_valid_time"),
            create_time=(
                row.get("r1_fact_create_time")
                or row.get("r1_fact_last_update_time")
                or row.get("r1_chunk_create_time")
                or row.get("r2_fact_create_time")
                or row.get("r2_fact_last_update_time")
                or row.get("r2_chunk_create_time")
            ),
            metadata={
                "relation_uuids": [r1_uuid, r2_uuid],
                "path_key": self._synthetic_path_key(row.get("start_uuid"), row.get("mid_uuid"), row.get("finish_uuid")),
                "start_entity": row.get("start_name"),
                "start_entity_uuid": row.get("start_uuid"),
                "middle_entity": row.get("mid_name"),
                "middle_entity_uuid": row.get("mid_uuid"),
                "target_entity": row.get("finish_name"),
                "target_entity_uuid": row.get("finish_uuid"),
                "edge_retrieval_sources": ["path_expansion"],
                "evidence_origin": row.get("r1_evidence_origin") or row.get("r2_evidence_origin"),
                "content_origin": row.get("r1_content_origin") or row.get("r2_content_origin"),
                "path_hops": 2,
                "evidence": [self._path_evidence_metadata(row, "r1"), self._path_evidence_metadata(row, "r2")],
                "score_formula": score_formula("path_score", SEMANTIC_PATH_SCORE_WEIGHTS),
                "score_components": components,
                **components,
            },
        )

    @staticmethod
    def _edge_content(row: Dict[str, Any]) -> str:
        return str(row.get("evidence_content") or "").strip()

    @staticmethod
    def _two_hop_content(row: Dict[str, Any]) -> str:
        return "\n".join(
            str(row.get(f"{prefix}_evidence_content") or "").strip()
            for prefix in ("r1", "r2")
            if str(row.get(f"{prefix}_evidence_content") or "").strip()
        )

    @staticmethod
    def _evidence_metadata(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "ori_fact_uuid": row.get("ori_fact_uuid"),
            "chunk_uuid": row.get("chunk_uuid"),
            "confidence": row.get("fact_confidence"),
            "importance": row.get("fact_importance"),
            "fact_create_time": row.get("fact_create_time"),
            "fact_last_update_time": row.get("fact_last_update_time"),
            "chunk_valid_time": row.get("chunk_valid_time"),
            "chunk_create_time": row.get("chunk_create_time"),
        }

    @classmethod
    def _path_evidence_metadata(cls, row: Dict[str, Any], prefix: str) -> Dict[str, Any]:
        return {
            "ori_fact_uuid": row.get(f"{prefix}_ori_fact_uuid"),
            "chunk_uuid": row.get(f"{prefix}_chunk_uuid"),
            "confidence": row.get(f"{prefix}_fact_confidence"),
            "importance": row.get(f"{prefix}_fact_importance"),
            "fact_create_time": row.get(f"{prefix}_fact_create_time"),
            "fact_last_update_time": row.get(f"{prefix}_fact_last_update_time"),
            "chunk_valid_time": row.get(f"{prefix}_chunk_valid_time"),
            "chunk_create_time": row.get(f"{prefix}_chunk_create_time"),
        }

    @classmethod
    def _edge_path(cls, row: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            cls._entity_path_node(row, "source"),
            {
                "label": "RELATES_TO",
                "uuid": row.get("relation_uuid") or cls._synthetic_relation_uuid(row.get("source_uuid"), row.get("target_uuid")),
                "relation": row.get("relation_label"),
                "evidence": cls._evidence_metadata(row),
            },
            cls._entity_path_node(row, "target"),
        ]

    @classmethod
    def _two_hop_path(cls, row: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            cls._entity_path_node(row, "start"),
            {
                "label": "RELATES_TO",
                "uuid": row.get("r1_uuid") or cls._synthetic_relation_uuid(row.get("start_uuid"), row.get("mid_uuid")),
                "relation": row.get("r1_relation"),
                "evidence": cls._path_evidence_metadata(row, "r1"),
            },
            cls._entity_path_node(row, "mid"),
            {
                "label": "RELATES_TO",
                "uuid": row.get("r2_uuid") or cls._synthetic_relation_uuid(row.get("mid_uuid"), row.get("finish_uuid")),
                "relation": row.get("r2_relation"),
                "evidence": cls._path_evidence_metadata(row, "r2"),
            },
            cls._entity_path_node(row, "finish"),
        ]

    @classmethod
    def _entity_path_node(cls, row: Dict[str, Any], prefix: str) -> Dict[str, Any]:
        return {
            "label": cls._semantic_label(row.get(f"{prefix}_labels")),
            "uuid": row.get(f"{prefix}_uuid"),
            "name": row.get(f"{prefix}_name"),
            "type": row.get(f"{prefix}_type"),
        }

    @staticmethod
    def _semantic_label(labels: Any) -> str:
        labels = list(labels or [])
        return "Entity" if "Entity" in labels else (labels[0] if labels else "Entity")

    @staticmethod
    def _endpoint_score(
        uuid: Any,
        name: Any,
        entity_score_map: Dict[str, float],
        query_text: str,
        query_entities: List[str],
    ) -> float:
        if uuid in entity_score_map:
            return clamp_score(entity_score_map[uuid])
        name_text = str(name or "")
        if name_text and name_text in str(query_text or ""):
            return 0.85
        if query_entities:
            return clamp_score(lexical_overlap_score(" ".join(query_entities), name_text) * 0.8)
        return 0.5

    @staticmethod
    def _path_edge_quality(row: Dict[str, Any], prefix: str) -> float:
        return compute_edge_quality_score(
            True,
            row.get(f"{prefix}_evidence_content"),
            row.get(f"{prefix}_ori_fact_uuid"),
            row.get(f"{prefix}_chunk_uuid"),
            row.get(f"{prefix}_fact_confidence"),
            row.get(f"{prefix}_fact_importance"),
        )

    @staticmethod
    def _path_time_score(row: Dict[str, Any], prefix: str, time_constraint: Dict[str, Any]) -> float:
        return compute_time_score(
            time_constraint,
            row.get(f"{prefix}_chunk_valid_time"),
        )

    @staticmethod
    def _should_expand_paths(
        sub_query: Dict[str, Any],
        entity_uuids: List[str],
        edge_candidates: Dict[str, Dict[str, Any]],
        edge_items: List[EvidenceItem],
        max_hops: int,
    ) -> bool:
        if max_hops < 2:
            return False
        if str(sub_query.get("relation_intent") or "") == "path":
            return True
        if len(entity_uuids) > 1 and not EntityRelationRetriever._has_direct_entity_pair(edge_candidates, entity_uuids):
            return True
        return max([item.local_score for item in edge_items] or [0.0]) < 0.62

    @staticmethod
    def _has_direct_entity_pair(edge_candidates: Dict[str, Dict[str, Any]], entity_uuids: List[str]) -> bool:
        entity_set = set(entity_uuids)
        return any(
            row.get("source_uuid") in entity_set and row.get("target_uuid") in entity_set
            for row in edge_candidates.values()
        )

    async def _legacy_entity_fact_fallback(
        self,
        role_id: str,
        query_text: str,
        query_entities: List[str],
        top_k: int,
    ) -> List[EvidenceItem]:
        query = """
        MATCH (entity:Entity {role_id: $role_id})
        WHERE ANY(name IN $query_entities WHERE entity.name CONTAINS name OR name CONTAINS entity.name)
        MATCH (chunk:ChunkNode {role_id: $role_id})-[:HAS_ENTITY]->(entity)
        MATCH (chunk)-[:HAS_FACT]->(original:OriginalFact {role_id: $role_id})
        RETURN
            entity.entity_uuid AS entity_uuid,
            original.ori_fact_uuid AS ori_fact_uuid,
            chunk.chunk_uuid AS chunk_uuid,
            chunk.valid_time AS valid_time,
            original.create_time AS create_time
        LIMIT $limit
        """
        rows = await self.manager.execute_query(
            query,
            {"role_id": role_id, "query_entities": query_entities, "limit": int(top_k)},
        )
        source_contents = await get_many_for_role(
            self.source_provider,
            [row.get("ori_fact_uuid") for row in rows if row.get("ori_fact_uuid")],
            role_id,
        )
        items: List[EvidenceItem] = []
        for row in rows:
            ori_fact_uuid = row.get("ori_fact_uuid")
            content = source_contents.get(str(ori_fact_uuid), "") if ori_fact_uuid else ""
            if not content:
                continue
            items.append(
                EvidenceItem(
                    source="relation",
                    content=content,
                    local_score=clamp_score(0.25 + lexical_overlap_score(query_text, content) * 0.45),
                    evidence_type="legacy_fact_entity_path",
                    entity_uuid=row.get("entity_uuid"),
                    ori_fact_uuid=ori_fact_uuid,
                    fact_uuid=ori_fact_uuid,
                    chunk_uuid=row.get("chunk_uuid"),
                    valid_time=row.get("valid_time"),
                    create_time=row.get("create_time"),
                    metadata={
                        "legacy_fallback": True,
                        "edge_retrieval_sources": ["legacy_entity_fact"],
                        "path_hops": 1,
                        "content_origin": CONTENT_ORIGIN,
                    },
                )
            )
        return items
