"""Milvus chunk vector retriever."""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Dict, List, MutableMapping, Optional, Tuple

from app.common.manager.neo4j_manager import Neo4jManager
from app.DBserver.milvus_repository.milvus_operate import MilvusCRUD
from app.retrieval.milvus_search import first_hit_page, quote_expr_value, search_raw_hits
from app.retrieval.models import EvidenceItem
from app.retrieval.score import VECTOR_SCORE_FORMULA, compute_vector_score, l2_distance_to_score, lexical_overlap_score
from app.retrieval.trace import error as trace_error
from app.retrieval.trace import record as trace_record
from app.retrieval.trace import row as trace_row
from app.retrieval.utils import hit_entity

logger = logging.getLogger(__name__)


class ChunkRetriever:
    def __init__(
        self,
        manager: Optional[Neo4jManager] = None,
        milvus_crud: Optional[MilvusCRUD] = None,
        embedding_client: Optional[Any] = None,
        reranker: Optional[Any] = None,
    ):
        self.manager = manager or Neo4jManager.get_instance()
        self.milvus_crud = milvus_crud or MilvusCRUD()
        self.embedding_client = embedding_client
        self.reranker = reranker

    async def retrieve(
        self,
        role_id: str,
        sub_query: Dict[str, Any],
        query_embedding: Optional[List[float]] = None,
        top_k: int = 10,
        trace: Optional[MutableMapping[str, Any]] = None,
    ) -> List[EvidenceItem]:
        query_text = str(sub_query.get("query") or "").strip()
        if query_embedding is None:
            try:
                if self.embedding_client is None:
                    from app.common.client.embedding_client import get_embedding_client

                    client = get_embedding_client()
                else:
                    client = self.embedding_client
                query_embedding = await client.embed(query_text)
            except Exception as exc:
                logger.warning("Chunk embedding failed, skip vector chunk search: %s", exc)
                trace_error(trace, "chunk_embedding", exc)
                return []

        hits = await self._search_milvus(role_id, query_embedding, top_k=top_k)
        hit_rows = list(hits.values())
        for raw_rank, row in enumerate(hit_rows, start=1):
            row.setdefault("raw_hit_rank", raw_rank)
            trace_record(trace, "raw_hits", trace_row(row, source="vector"))
        chunk_map = await self._load_chunks(
            role_id,
            [row["chunk_uuid"] for row in hit_rows if row.get("chunk_uuid")],
        )
        items: List[EvidenceItem] = []
        for row in hit_rows:
            chunk = chunk_map.get(row.get("chunk_uuid"), {})
            bound_fact_uuids = [str(value) for value in chunk.get("ori_fact_uuids") or [] if value]
            expected_fact_uuid = str(row.get("fact_uuid") or "")
            if len(bound_fact_uuids) != 1 or (expected_fact_uuid and expected_fact_uuid != bound_fact_uuids[0]):
                metrics = trace.setdefault("metrics", {}) if trace is not None else {}
                metrics["binding_unbound"] = int(metrics.get("binding_unbound") or 0) + 1
                continue
            summary = self._summary_text(chunk.get("summary"))
            if not summary:
                logger.debug("Chunk hit has no role-scoped HAS_FACT summary, skip: chunk_uuid=%s", row.get("chunk_uuid"))
                continue
            rerank_score = await self._rerank(query_text, summary)
            local_score = compute_vector_score(rerank_score, row.get("milvus_score", 0.0))
            item = EvidenceItem(
                    source="vector",
                    content=summary,
                    local_score=local_score,
                    evidence_type="original_fact_chunk",
                    chunk_uuid=row.get("chunk_uuid"),
                    fact_uuid=bound_fact_uuids[0],
                    ori_fact_uuid=bound_fact_uuids[0],
                    valid_time=chunk.get("valid_time"),
                    create_time=chunk.get("create_time"),
                    metadata={
                        "summary": summary,
                        "hash_val": chunk.get("hash_val"),
                        "milvus_score": row.get("milvus_score"),
                        "rerank_score": rerank_score,
                        "score_formula": VECTOR_SCORE_FORMULA,
                        "score_components": {
                            "rerank_score": rerank_score,
                            "milvus_score": row.get("milvus_score", 0.0),
                        },
                        "vector_fields": sorted(row.get("vector_fields", [])),
                        "chunk_missing": not bool(chunk),
                        "content_origin": "chunk_node.summary_via_has_fact",
                        "raw_hit_rank": row.get("raw_hit_rank"),
                        "route_raw_hit_ranks": {"vector": row.get("raw_hit_rank")},
                        "route_retrieval_scores": {"vector": row.get("milvus_score")},
                    },
                )
            items.append(item)
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

    async def _search_milvus(
        self,
        role_id: str,
        query_embedding: List[float],
        top_k: int,
    ) -> Dict[Tuple[str, Optional[int]], Dict[str, Any]]:
        loop = asyncio.get_running_loop()
        merged: Dict[Tuple[str, Optional[int]], Dict[str, Any]] = {}

        async def search_field(vector_field: str) -> Tuple[str, List[Any]]:
            try:
                result = await loop.run_in_executor(
                    None,
                    lambda field=vector_field: search_raw_hits(
                        self.milvus_crud,
                        collection_name="chunk_schema",
                        embedding=query_embedding,
                        vector_field=field,
                        top_k=top_k,
                        expr=f"role_id == {quote_expr_value(role_id)}",
                    ),
                )
            except Exception as exc:
                logger.warning("Milvus chunk search failed: field=%s error=%s", vector_field, exc)
                return vector_field, []
            return vector_field, first_hit_page(result)

        field_results = await asyncio.gather(
            search_field("dia_embedding"),
            search_field("summary_embedding"),
        )
        for vector_field, hits in field_results:
            for hit in hits:
                entity = hit_entity(hit)
                chunk_uuid = entity.get("chunk_uuid")
                if not chunk_uuid:
                    continue
                key = (chunk_uuid, None)
                score = l2_distance_to_score(getattr(hit, "distance", None))
                if key not in merged:
                    merged[key] = {
                        "chunk_uuid": chunk_uuid,
                        "fact_uuid": entity.get("fact_uuid"),
                        "milvus_score": score,
                        "vector_fields": {vector_field},
                    }
                else:
                    merged[key]["milvus_score"] = min(max(merged[key]["milvus_score"], score) + 0.05, 1.0)
                    merged[key]["vector_fields"].add(vector_field)
                    if not merged[key].get("fact_uuid"):
                        merged[key]["fact_uuid"] = entity.get("fact_uuid")
        return merged

    async def _load_chunks(self, role_id: str, chunk_uuids: List[str]) -> Dict[str, Dict[str, Any]]:
        unique_chunk_uuids = list(dict.fromkeys(str(value) for value in chunk_uuids if value))
        if not unique_chunk_uuids:
            return {}

        query = """
        MATCH (c:ChunkNode {role_id: $role_id})-[:HAS_FACT]->(o:OriginalFact {role_id: $role_id})
        WHERE c.chunk_uuid IN $chunk_uuids
        WITH c, collect(DISTINCT o.ori_fact_uuid) AS ori_fact_uuids
        RETURN
            c.chunk_uuid AS chunk_uuid,
            c.summary AS summary,
            c.valid_time AS valid_time,
            c.create_time AS create_time,
            c.hash_val AS hash_val,
            ori_fact_uuids
        """
        rows = await self.manager.execute_query(
            query,
            {"role_id": role_id, "chunk_uuids": unique_chunk_uuids},
        )
        chunks: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            chunk = dict(row)
            chunk_uuid = chunk.get("chunk_uuid")
            if chunk_uuid and chunk_uuid not in chunks:
                chunks[chunk_uuid] = chunk

        return chunks

    async def _load_chunk(self, role_id: str, chunk_uuid: Optional[str]) -> Dict[str, Any]:
        if not chunk_uuid:
            return {}
        query = """
        MATCH (c:ChunkNode {role_id: $role_id, chunk_uuid: $chunk_uuid})
        RETURN
            c.chunk_uuid AS chunk_uuid,
            c.contents AS contents,
            c.summary AS summary,
            c.valid_time AS valid_time,
            c.create_time AS create_time,
            c.hash_val AS hash_val
        LIMIT 1
        """
        rows = await self.manager.execute_query(query, {"role_id": role_id, "chunk_uuid": chunk_uuid})
        return dict(rows[0]) if rows else {}

    @staticmethod
    def _summary_text(summaries: Any) -> str:
        if isinstance(summaries, str):
            return summaries.strip()
        summary_list = summaries if isinstance(summaries, list) else []
        return "\n".join(str(item) for item in summary_list if item).strip()

    async def _rerank(self, query_text: str, content: str) -> float:
        if self.reranker is not None and hasattr(self.reranker, "score"):
            try:
                value = self.reranker.score(query_text, content)
                if inspect.isawaitable(value):
                    value = await value
                return max(0.0, min(float(value), 1.0))
            except Exception as exc:
                logger.warning("Reranker failed, fallback to lexical score: %s", exc)
        return lexical_overlap_score(query_text, content)
