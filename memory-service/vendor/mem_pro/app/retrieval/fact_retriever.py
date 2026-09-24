"""Fact hybrid retriever."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, MutableMapping, Optional, Tuple

from app.common.manager.neo4j_manager import Neo4jManager
from app.DBserver.milvus_repository.milvus_operate import MilvusCRUD
from app.retrieval.fact_source_provider import CONTENT_ORIGIN, OriginalFactSourceProvider, get_many_for_role
from app.retrieval.milvus_search import first_hit_page, quote_expr_value, search_raw_hits
from app.retrieval.models import EvidenceItem
from app.retrieval.score import (
    FACT_SCORE_WEIGHTS,
    compute_entity_match_score,
    compute_fact_score,
    compute_fact_quality_score,
    compute_time_score,
    l2_distance_to_score,
    lexical_overlap_score,
    normalize_scores,
    score_formula,
)
from app.retrieval.utils import clean_text_list, escape_lucene_fulltext_query, hit_entity, node_to_dict
from app.retrieval.trace import error as trace_error
from app.retrieval.trace import record as trace_record
from app.retrieval.trace import row as trace_row

logger = logging.getLogger(__name__)


class FactRetriever:
    def __init__(
        self,
        manager: Optional[Neo4jManager] = None,
        milvus_crud: Optional[MilvusCRUD] = None,
        embedding_client: Optional[Any] = None,
        source_provider: Optional[Any] = None,
    ):
        self.manager = manager or Neo4jManager.get_instance()
        self.milvus_crud = milvus_crud or MilvusCRUD()
        self.embedding_client = embedding_client
        self.source_provider = source_provider or OriginalFactSourceProvider()

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
        keywords = clean_text_list(sub_query.get("keywords") or [query_text])
        entities = clean_text_list(sub_query.get("entities") or [])
        time_constraint = sub_query.get("time") or {}
        candidate_top_k = max(top_k * 2, 20)

        candidates: Dict[Tuple[str, str], Dict[str, Any]] = {}
        text_search_kwargs: Dict[str, Any] = {"top_k": candidate_top_k}
        if trace is not None:
            text_search_kwargs["trace"] = trace
        text_rows = await self._text_search(role_id, query_text, keywords, **text_search_kwargs)
        for raw_rank, row in enumerate(text_rows, start=1):
            row.setdefault("raw_hit_rank", raw_rank)
            key = (row["kind"], row["uuid"])
            existing = candidates.get(key)
            if existing is None:
                candidates[key] = dict(row)
            else:
                existing["text_score"] = max(
                    float(existing.get("text_score") or 0.0),
                    float(row.get("text_score") or 0.0),
                )
                for field in ("chunk_uuid", "valid_time", "chunk_create_time", "lexical_chunk_summary"):
                    if existing.get(field) in (None, "") and row.get(field) not in (None, ""):
                        existing[field] = row.get(field)

        vector_rows = await self._vector_search(role_id, query_text, query_embedding, top_k=candidate_top_k)
        for raw_rank, row in enumerate(vector_rows, start=1):
            row.setdefault("raw_hit_rank", raw_rank)
            trace_record(trace, "raw_hits", trace_row(row, source="fact"))
            key = (row["kind"], row["uuid"])
            if key in candidates:
                candidates[key]["vector_score"] = max(
                    candidates[key].get("vector_score", 0.0),
                    row.get("vector_score", 0.0),
                )
            else:
                candidates[key] = row

        candidate_list = list(candidates.values())
        source_ids = [
            candidate.get("ori_fact_uuid") or candidate.get("uuid")
            for candidate in candidate_list
            if candidate.get("ori_fact_uuid") or candidate.get("uuid")
        ]
        source_contents = await get_many_for_role(self.source_provider, source_ids, role_id)
        contexts = await self._load_contexts(role_id, candidate_list)

        items: List[EvidenceItem] = []
        for candidate in candidate_list:
            text_score = candidate.get("text_score")
            vector_score = candidate.get("vector_score")
            if text_score is not None and vector_score is not None:
                retrieval_score = min(max(float(text_score), float(vector_score)) + 0.12, 1.0)
            else:
                retrieval_score = float(text_score if text_score is not None else vector_score or 0.0)

            context_key = candidate.get("ori_fact_uuid") or candidate.get("uuid")
            context = contexts.get(context_key) or {}
            if not context or not context.get("chunk_uuid"):
                fallback_context = await self._load_context(role_id, candidate)
                if fallback_context:
                    context = {**context, **fallback_context}
            trace_record(
                trace,
                "has_fact_bindings",
                trace_row(
                    {
                        **candidate,
                        **context,
                        "ori_fact_uuid": context_key,
                    },
                    source="fact",
                ),
            )
            # Preserve a directly matched ChunkNode provenance (for example the
            # lexical ChunkNode.summary backstop), while keeping all fact-level
            # valid_time values collected from HAS_FACT for temporal scoring.
            hydrated_candidate = {**context, **candidate}
            if context.get("valid_times"):
                hydrated_candidate["valid_times"] = context["valid_times"]
            ori_fact_uuid = hydrated_candidate.get("ori_fact_uuid") or hydrated_candidate.get("uuid")
            content = source_contents.get(str(ori_fact_uuid), "") if ori_fact_uuid else ""
            if not content:
                continue
            hydrated_candidate["content"] = content
            hydrated_candidate["content_origin"] = CONTENT_ORIGIN
            item = self._to_evidence(
                    candidate=hydrated_candidate,
                    retrieval_score=retrieval_score,
                    entities=entities,
                    time_constraint=time_constraint,
                    current_time=current_time,
                )
            items.append(item)
            trace_record(
                trace,
                "route_candidates",
                trace_row(
                    {
                        "chunk_uuid": item.chunk_uuid,
                        "ori_fact_uuid": item.ori_fact_uuid,
                        "fact_uuid": item.fact_uuid,
                        "valid_time": item.valid_time,
                        "local_score": item.local_score,
                    },
                    source=item.source,
                ),
            )
        return sorted(items, key=lambda item: item.local_score, reverse=True)[:top_k]

    async def _text_search(
        self,
        role_id: str,
        query_text: str,
        keywords: List[str],
        top_k: int,
        trace: Optional[MutableMapping[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        try:
            original_rows = await self._original_fulltext(role_id, query_text, top_k)
            rows.extend(original_rows)
            for row in original_rows:
                trace_record(trace, "raw_hits", trace_row(row, source="fact"))
        except Exception as exc:
            logger.warning("Fact fulltext search failed, fallback to contains: %s", exc)
            trace_error(trace, "original_fact_summary_fulltext", exc)

        try:
            rows.extend(await self._chunk_summary_fulltext(role_id, query_text, top_k, trace=trace))
        except Exception as exc:
            logger.warning("Chunk summary fulltext search failed: %s", exc)
            trace_error(trace, "chunk_summary_fulltext", exc)

        if not rows:
            contains_rows = await self._contains_search(role_id, keywords, top_k)
            rows.extend(contains_rows)
            for row in contains_rows:
                trace_record(trace, "raw_hits", trace_row(row, source="fact"))

        normalize_scores(rows, "text_score")
        return rows[: top_k * 2]

    async def _chunk_summary_fulltext(
        self,
        role_id: str,
        query_text: str,
        top_k: int,
        trace: Optional[MutableMapping[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        fulltext_query = escape_lucene_fulltext_query(query_text)
        if not fulltext_query:
            return []
        query = """
        CALL db.index.fulltext.queryNodes($index_name, $query_text)
        YIELD node, score
        WHERE node:ChunkNode AND node.role_id = $role_id
        OPTIONAL MATCH (node)-[:HAS_FACT]->(original:OriginalFact)
        WITH node, score, collect(DISTINCT CASE
            WHEN original IS NOT NULL AND original.role_id = $role_id THEN {
                ori_fact_uuid: original.ori_fact_uuid,
                summary: original.summary,
                confidence: original.confidence,
                importance: original.importance,
                create_time: original.create_time,
                last_update_time: original.last_update_time,
                used_count: original.used_count
            }
            ELSE NULL
        END) AS fact_records
        WITH node, score, [record IN fact_records WHERE record IS NOT NULL] AS fact_records
        RETURN
            node.chunk_uuid AS chunk_uuid,
            node.summary AS chunk_summary,
            node.valid_time AS valid_time,
            node.create_time AS chunk_create_time,
            node.hash_val AS hash_val,
            fact_records,
            score AS text_score
        ORDER BY score DESC, node.chunk_uuid ASC
        LIMIT $limit
        """
        result = await self.manager.execute_query(
            query,
            {
                "index_name": "chunk_summary_fulltext",
                "query_text": fulltext_query,
                "role_id": role_id,
                "limit": int(top_k),
            },
        )
        rows: List[Dict[str, Any]] = []
        for raw_row in result or []:
            row = dict(raw_row)
            metrics = trace.setdefault("metrics", {}) if trace is not None else {}
            metrics["chunk_summary_fulltext_hits"] = int(metrics.get("chunk_summary_fulltext_hits") or 0) + 1
            trace_record(trace, "raw_hits", trace_row(row, source="fact"))
            records = [record for record in row.get("fact_records") or [] if record]
            if not records:
                metrics["binding_unbound"] = int(metrics.get("binding_unbound") or 0) + 1
                continue
            if len(records) != 1:
                metrics["binding_ambiguity"] = int(metrics.get("binding_ambiguity") or 0) + 1
                continue
            record = records[0]
            row.update(record)
            row.update(
                {
                    "kind": "original",
                    "uuid": record.get("ori_fact_uuid"),
                    "ori_fact_uuid": record.get("ori_fact_uuid"),
                    "fact_uuid": record.get("ori_fact_uuid"),
                    "summary": record.get("summary"),
                    "matched_field": "chunk_summary",
                    "lexical_chunk_summary": row.get("chunk_summary"),
                }
            )
            trace_record(trace, "has_fact_bindings", trace_row(row, source="fact"))
            rows.append(row)
        return rows

    async def _original_fulltext(self, role_id: str, query_text: str, top_k: int) -> List[Dict[str, Any]]:
        fulltext_query = escape_lucene_fulltext_query(query_text)
        if not fulltext_query:
            return []
        rows: List[Dict[str, Any]] = []
        for index_name, field_name in (
            ("original_fact_summary_fulltext", "summary"),
        ):
            query = """
            CALL db.index.fulltext.queryNodes($index_name, $query_text)
            YIELD node, score
            WHERE node:OriginalFact AND node.role_id = $role_id
            RETURN
                node.ori_fact_uuid AS uuid,
                node.ori_fact_uuid AS ori_fact_uuid,
                node.summary AS summary,
                node.confidence AS confidence,
                node.importance AS importance,
                node.create_time AS create_time,
                node.last_update_time AS last_update_time,
                node.used_count AS used_count,
                score AS text_score
            LIMIT $limit
            """
            result = await self.manager.execute_query(
                query,
                {
                    "index_name": index_name,
                    "query_text": fulltext_query,
                    "role_id": role_id,
                    "limit": int(top_k),
                },
            )
            for row in result:
                row["kind"] = "original"
                row["matched_field"] = field_name
                rows.append(row)
        return rows

    async def _contains_search(self, role_id: str, keywords: List[str], top_k: int) -> List[Dict[str, Any]]:
        if not keywords:
            return []
        original_query = """
        MATCH (o:OriginalFact {role_id: $role_id})
        WHERE ANY(k IN $keywords WHERE o.summary CONTAINS k)
        RETURN
            o.ori_fact_uuid AS uuid,
            o.ori_fact_uuid AS ori_fact_uuid,
            o.summary AS summary,
            o.confidence AS confidence,
            o.importance AS importance,
            o.create_time AS create_time,
            o.last_update_time AS last_update_time,
            o.used_count AS used_count
        LIMIT $limit
        """
        params = {"role_id": role_id, "keywords": keywords, "limit": int(top_k)}
        rows = []
        for row in await self.manager.execute_query(original_query, params):
            row["kind"] = "original"
            row["text_score"] = lexical_overlap_score(" ".join(keywords), str(row.get("summary") or ""))
            rows.append(row)
        return rows

    async def _vector_search(
        self,
        role_id: str,
        query_text: str,
        query_embedding: Optional[List[float]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        if query_embedding is None:
            try:
                if self.embedding_client is None:
                    from app.common.client.embedding_client import get_embedding_client

                    client = get_embedding_client()
                else:
                    client = self.embedding_client
                query_embedding = await client.embed(query_text)
            except Exception as exc:
                logger.warning("Fact embedding failed, skip vector fact search: %s", exc)
                return []

        loop = asyncio.get_running_loop()
        rows: List[Dict[str, Any]] = []
        collection_name = "ori_fact_schema"
        try:
            result = await loop.run_in_executor(
                None,
                lambda: search_raw_hits(
                    self.milvus_crud,
                    collection_name=collection_name,
                    embedding=query_embedding,
                    vector_field="summary_embedding",
                    top_k=top_k,
                    expr=f"role_id == {quote_expr_value(role_id)}",
                ),
            )
        except Exception as exc:
            logger.warning("Milvus fact search failed: collection=%s error=%s", collection_name, exc)
            return rows
        for hit in first_hit_page(result):
            entity = hit_entity(hit)
            uuid = entity.get("ori_fact_uuid") or entity.get("uuid")
            if not uuid:
                continue
            rows.append(
                {
                    "kind": "original",
                    "uuid": uuid,
                    "ori_fact_uuid": uuid,
                    "summary": entity.get("summary", ""),
                    "vector_score": l2_distance_to_score(getattr(hit, "distance", None)),
                }
            )
        return rows

    async def _load_contexts(self, role_id: str, candidates: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        ori_fact_uuids = list(
            dict.fromkeys(
                str(candidate.get("ori_fact_uuid") or candidate.get("uuid"))
                for candidate in candidates
                if candidate.get("ori_fact_uuid") or candidate.get("uuid")
            )
        )
        if not ori_fact_uuids:
            return {}

        query = """
        MATCH (o:OriginalFact {role_id: $role_id})
        WHERE o.ori_fact_uuid IN $ori_fact_uuids
        OPTIONAL MATCH (c:ChunkNode {role_id: $role_id})-[:HAS_FACT]->(o)
        RETURN
            o.ori_fact_uuid AS ori_fact_uuid,
            o.summary AS summary,
            o.confidence AS confidence,
            o.importance AS importance,
            o.create_time AS create_time,
            o.last_update_time AS last_update_time,
            o.used_count AS used_count,
            c.chunk_uuid AS chunk_uuid,
            c.valid_time AS valid_time,
            c.create_time AS chunk_create_time
        """
        rows = await self.manager.execute_query(
            query,
            {"role_id": role_id, "ori_fact_uuids": ori_fact_uuids},
        )
        contexts: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            context = dict(row)
            ori_fact_uuid = context.get("ori_fact_uuid")
            if not ori_fact_uuid:
                continue
            existing = contexts.get(ori_fact_uuid)
            valid_time = context.get("valid_time")
            if existing is None:
                context["valid_times"] = [valid_time] if valid_time not in (None, "") else []
                contexts[ori_fact_uuid] = context
                continue
            if valid_time not in (None, "") and valid_time not in existing.setdefault("valid_times", []):
                existing["valid_times"].append(valid_time)
            current_key = (
                str(existing.get("valid_time") or "~"),
                str(existing.get("chunk_uuid") or ""),
            )
            candidate_key = (
                str(context.get("valid_time") or "~"),
                str(context.get("chunk_uuid") or ""),
            )
            if context.get("chunk_uuid") and candidate_key < current_key:
                for key in ("chunk_uuid", "chunk_create_time", "valid_time", "fact_uuid"):
                    if context.get(key) not in (None, ""):
                        existing[key] = context.get(key)

        for context in contexts.values():
            context["valid_times"] = sorted(
                context.get("valid_times") or [],
                key=lambda value: (str(value) if value is not None else ""),
            )
            if context["valid_times"]:
                context["valid_time"] = context["valid_times"]

        bindings = await self._find_chunk_bindings(role_id, ori_fact_uuids)
        for ori_fact_uuid, binding in bindings.items():
            context = contexts.setdefault(ori_fact_uuid, {"ori_fact_uuid": ori_fact_uuid})
            for key, value in binding.items():
                if context.get(key) in (None, ""):
                    context[key] = value
        return contexts

    async def _load_context(self, role_id: str, candidate: Dict[str, Any]) -> Dict[str, Any]:
        query = """
        MATCH (o:OriginalFact {role_id: $role_id, ori_fact_uuid: $ori_fact_uuid})
        OPTIONAL MATCH (c:ChunkNode {role_id: $role_id})-[:HAS_FACT]->(o)
        RETURN
            o.ori_fact_uuid AS ori_fact_uuid,
            o.summary AS summary,
            o.confidence AS confidence,
            o.importance AS importance,
            o.create_time AS create_time,
            o.last_update_time AS last_update_time,
            o.used_count AS used_count,
            c.chunk_uuid AS chunk_uuid,
            c.valid_time AS valid_time,
            c.create_time AS chunk_create_time
        ORDER BY c.valid_time ASC, c.chunk_uuid ASC
        LIMIT 1
        """
        rows = await self.manager.execute_query(
            query,
            {"role_id": role_id, "ori_fact_uuid": candidate.get("ori_fact_uuid") or candidate.get("uuid")},
        )
        context = dict(rows[0]) if rows else {}
        ori_fact_uuid = context.get("ori_fact_uuid") or candidate.get("ori_fact_uuid") or candidate.get("uuid")
        binding = await self._find_chunk_binding(role_id, ori_fact_uuid)
        for key, value in binding.items():
            if context.get(key) in (None, ""):
                context[key] = value
        return context

    async def _find_chunk_binding(self, role_id: str, ori_fact_uuid: Optional[str]) -> Dict[str, Any]:
        if not ori_fact_uuid:
            return {}
        loop = asyncio.get_running_loop()
        try:
            query_method = getattr(self.milvus_crud, "query_", None) or getattr(self.milvus_crud, "query", None)
            if query_method is None:
                return {}
            rows = await loop.run_in_executor(
                None,
                lambda: query_method(
                    "chunk_schema",
                    f"role_id == {quote_expr_value(role_id)} and fact_uuid == {quote_expr_value(ori_fact_uuid)}",
                    output_fields=["chunk_uuid", "fact_uuid"],
                ),
            )
        except Exception:
            return {}
        if not rows:
            return {}
        return {
            "chunk_uuid": rows[0].get("chunk_uuid"),
            "fact_uuid": rows[0].get("fact_uuid"),
        }

    async def _find_chunk_bindings(self, role_id: str, ori_fact_uuids: List[str]) -> Dict[str, Dict[str, Any]]:
        fact_uuids = list(dict.fromkeys(str(value) for value in ori_fact_uuids if value))
        if not fact_uuids:
            return {}
        values = ", ".join(quote_expr_value(value) for value in fact_uuids)
        loop = asyncio.get_running_loop()
        try:
            query_method = getattr(self.milvus_crud, "query_", None) or getattr(self.milvus_crud, "query", None)
            if query_method is None:
                return {}
            rows = await loop.run_in_executor(
                None,
                lambda: query_method(
                    "chunk_schema",
                    f"role_id == {quote_expr_value(role_id)} and fact_uuid in [{values}]",
                    output_fields=["chunk_uuid", "fact_uuid"],
                ),
            )
        except Exception:
            return {}

        bindings: Dict[str, Dict[str, Any]] = {}
        for row in rows or []:
            fact_uuid = row.get("fact_uuid")
            if fact_uuid and fact_uuid not in bindings:
                bindings[fact_uuid] = {
                    "chunk_uuid": row.get("chunk_uuid"),
                    "fact_uuid": fact_uuid,
                }
        return bindings

    def _to_evidence(
        self,
        candidate: Dict[str, Any],
        retrieval_score: float,
        entities: List[str],
        time_constraint: Dict[str, Any],
        current_time: Any,
    ) -> EvidenceItem:
        content = str(candidate.get("content") or "").strip()
        evidence_type = "original_fact"
        entity_score = compute_entity_match_score(entities, content)
        quality_score = compute_fact_quality_score(
            evidence_type,
            candidate.get("importance", 0.0),
            candidate.get("status"),
            candidate.get("ddl"),
            current_time,
        )
        valid_times = candidate.get("valid_times") or candidate.get("valid_time")
        time_score = compute_time_score(time_constraint, valid_times)

        local_score = compute_fact_score(
            retrieval_score=retrieval_score,
            entities=entities,
            content=content,
            evidence_type=evidence_type,
            importance=candidate.get("importance", 0.0),
            status=candidate.get("status"),
            ddl=candidate.get("ddl"),
            time_constraint=time_constraint,
            valid_time=valid_times,
            current_time=current_time,
        )
        return EvidenceItem(
            source="fact",
            content=content,
            local_score=local_score,
            evidence_type=evidence_type,
            ori_fact_uuid=candidate.get("ori_fact_uuid") or candidate.get("uuid"),
            chunk_uuid=candidate.get("chunk_uuid"),
            fact_uuid=candidate.get("fact_uuid") or candidate.get("ori_fact_uuid") or candidate.get("uuid"),
            valid_time=valid_times,
            create_time=candidate.get("create_time"),
            metadata={
                "score_formula": score_formula("fact_score", FACT_SCORE_WEIGHTS),
                "score_components": {
                    "retrieval_score": retrieval_score,
                    "entity_match_score": entity_score,
                    "fact_quality_score": quality_score,
                    "time_score": time_score,
                    "time_status": "unknown" if not valid_times else "known",
                },
                "retrieval_score": retrieval_score,
                "text_score": candidate.get("text_score"),
                "vector_score": candidate.get("vector_score"),
                "matched_field": candidate.get("matched_field"),
                "lexical_chunk_summary": candidate.get("lexical_chunk_summary"),
                "confidence": candidate.get("confidence"),
                "importance": candidate.get("importance"),
                "content_origin": candidate.get("content_origin") or CONTENT_ORIGIN,
                "raw_hit_rank": candidate.get("raw_hit_rank"),
                "route_raw_hit_ranks": {"fact": candidate.get("raw_hit_rank")},
                "route_retrieval_scores": {"fact": retrieval_score},
            },
        )
