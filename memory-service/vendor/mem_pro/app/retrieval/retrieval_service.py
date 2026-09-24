"""Unified retrieval service."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from app.retrieval.merge import merge_evidence_items
from app.retrieval.models import EvidenceItem, RetrievalResult, json_safe
from app.retrieval.prompt_builder import PromptBuilder
from app.retrieval.score import compute_final_score
from app.retrieval.trace import evidence as trace_evidence
from app.retrieval.trace import new_trace
from app.retrieval.trace import record as trace_record

if TYPE_CHECKING:
    from app.retrieval.query_analyzer import QueryAnalyzer
    from app.retrieval.fact_retriever import FactRetriever
    from app.retrieval.entity_relation_retriever import EntityRelationRetriever
    from app.retrieval.chunk_retriever import ChunkRetriever
    from app.retrieval.profile_provider import ProfileProvider
    from app.memory.fact_node.fact_graph.fact_repository import FactGraphRepository

logger = logging.getLogger(__name__)

PROFILE_SOURCE = "main.final_main.Profile_main.profile_for_retrieval"


class RetrievalService:
    def __init__(
        self,
        analyzer: Optional[QueryAnalyzer] = None,
        fact_retriever: Optional[FactRetriever] = None,
        relation_retriever: Optional[EntityRelationRetriever] = None,
        chunk_retriever: Optional[ChunkRetriever] = None,
        prompt_builder: Optional[PromptBuilder] = None,
        profile_provider: Optional[ProfileProvider] = None,
        embedding_client: Optional[Any] = None,
        fact_repository: Optional[Any] = None,
        fact_store: Optional[Any] = None,
        use_llm_analyzer: bool = False,
        mark_used: bool = True,
        mark_used_mode: str = "background",
        max_sub_query_concurrency: int = 2,
    ):
        self.embedding_client = embedding_client
        if analyzer is None:
            from app.retrieval.query_analyzer import QueryAnalyzer

            analyzer = QueryAnalyzer(use_llm=use_llm_analyzer)
        if fact_retriever is None:
            from app.retrieval.fact_retriever import FactRetriever

            fact_retriever = FactRetriever(embedding_client=embedding_client)
        if relation_retriever is None:
            from app.retrieval.entity_relation_retriever import EntityRelationRetriever

            relation_retriever = EntityRelationRetriever(embedding_client=embedding_client)
        if chunk_retriever is None:
            from app.retrieval.chunk_retriever import ChunkRetriever

            chunk_retriever = ChunkRetriever(embedding_client=embedding_client)
        if profile_provider is None:
            from app.retrieval.profile_provider import ProfileProvider

            profile_provider = ProfileProvider()

        self.analyzer = analyzer
        self.fact_retriever = fact_retriever
        self.relation_retriever = relation_retriever
        self.chunk_retriever = chunk_retriever
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.profile_provider = profile_provider
        self.fact_repository = fact_repository
        self.fact_store = fact_store
        self.mark_used = mark_used
        self.mark_used_mode = self._normalize_mark_used_mode(mark_used_mode)
        self.max_sub_query_concurrency = max(1, int(max_sub_query_concurrency or 1))
        self._mark_used_tasks: set[asyncio.Task[Any]] = set()

    async def retrieve(
        self,
        role_id: str,
        query_text: str,
        current_time: Optional[datetime | str] = None,
        top_k: int = 12,
        init_indexes: bool = False,
        target_object: str = "",
    ) -> RetrievalResult:
        normalized_now = current_time or datetime.now(timezone.utc)
        if init_indexes:
            await self.ensure_indexes()

        request_cache = self._new_request_cache()
        profile_context = await self._get_profile_context(role_id)
        user_profile = str(profile_context.get("content") or "")
        analysis = await self._analyze_query(
            role_id,
            query_text,
            normalized_now,
            user_profile,
            target_object,
            request_cache=request_cache,
        )
        sub_queries = analysis.get("sub_queries") or []

        all_items: List[EvidenceItem] = []
        request_trace = new_trace()
        debug = {
            "fact_count": 0,
            "relation_count": 0,
            "vector_count": 0,
            "errors": [],
            "route_diagnostics": [],
            "binding_ambiguity": 0,
            "binding_unbound": 0,
            "candidate_evidence": [],
            "trace": request_trace,
            "analysis_debug": analysis.get("analysis_debug") or {},
            "profile_debug": {
                "available": bool(profile_context.get("available", False)),
                "source": str(profile_context.get("source") or ""),
                "error": str(profile_context.get("error") or ""),
            },
        }

        sub_query_results = await self._process_sub_queries(
            role_id=role_id,
            query_text=query_text,
            sub_queries=sub_queries,
            current_time=normalized_now,
            top_k=top_k,
            request_cache=request_cache,
        )
        for result in sub_query_results:
            all_items.extend(result["items"])
            debug["errors"].extend(result["errors"])
            debug["candidate_evidence"].extend(result.get("candidate_evidence") or [])
            debug["route_diagnostics"].extend(result.get("route_diagnostics") or [])
            request_trace.setdefault("sub_queries", []).append(result.get("trace") or {})
            for diagnostic in result.get("route_diagnostics") or []:
                metrics = diagnostic.get("metrics") or {}
                debug["binding_ambiguity"] += int(metrics.get("binding_ambiguity") or 0)
                debug["binding_unbound"] += int(metrics.get("binding_unbound") or 0)

        for sub_query_trace in request_trace.get("sub_queries") or []:
            for route_trace in sub_query_trace.get("routes") or []:
                for stage in ("raw_hits", "has_fact_bindings", "route_candidates"):
                    request_trace["stages"][stage].extend(
                        route_trace.get("stages", {}).get(stage, [])
                    )

        debug["fact_count"] = sum(1 for item in all_items if item.source == "fact")
        debug["relation_count"] = sum(1 for item in all_items if item.source == "relation")
        debug["vector_count"] = sum(1 for item in all_items if item.source == "vector")

        merged = merge_evidence_items(all_items)
        debug["merged_count"] = len(merged)

        for item in merged:
            routes = item.metadata.get("sub_query_routes") or ["fact", "relation", "vector"]
            time_constraint = item.metadata.get("time_constraint") or {}
            compute_final_score(item, routes, time_constraint)
            trace_record(
                request_trace,
                "merge",
                trace_evidence(item, identity=self._item_identity(item)),
            )

        selected = self._select_evidence(merged, sub_queries, top_k)
        selected_ids = {self._item_identity(item) for item in selected}
        merged_by_identity = {self._item_identity(item): item for item in merged}
        for item in selected:
            trace_record(
                request_trace,
                "selected",
                trace_evidence(item, identity=self._item_identity(item)),
            )
        for trace in debug.get("candidate_evidence") or []:
            identity = trace.pop("_identity", "")
            merged_item = merged_by_identity.get(identity)
            trace["final_score"] = merged_item.final_score if merged_item is not None else 0.0
            trace["entered_selected_evidence"] = identity in selected_ids
        debug["candidate_evidence"] = sorted(
            debug.get("candidate_evidence") or [],
            key=lambda item: (
                int(item.get("sub_query_index") or 0),
                str(item.get("route") or ""),
                int(item.get("route_rank") or 0),
            ),
        )
        await self._mark_selected_used(role_id, selected, normalized_now)

        prompt_context = self._build_prompt_context(
            query_text=query_text,
            sub_queries=sub_queries,
            evidence_items=selected,
            max_items=top_k,
            user_profile=user_profile,
        )
        return RetrievalResult(
            query=query_text,
            sub_queries=sub_queries,
            evidence_items=selected,
            prompt_context=prompt_context,
            debug=debug,
        )

    def retrieve_sync(
        self,
        role_id: str,
        query_text: str,
        current_time: Optional[datetime | str] = None,
        top_k: int = 12,
        init_indexes: bool = False,
        target_object: str = "",
    ) -> RetrievalResult:
        return asyncio.run(
            self.retrieve(
                role_id=role_id,
                query_text=query_text,
                current_time=current_time,
                top_k=top_k,
                init_indexes=init_indexes,
                target_object=target_object,
            )
        )

    async def ensure_indexes(self) -> None:
        from app.common.indexing.neo4j_schema import init_retrieval_indexes

        await init_retrieval_indexes()

    async def _get_profile_context(self, role_id: str) -> Dict[str, Any]:
        try:
            profile_context = await self.profile_provider.get_profile(role_id)
        except Exception as exc:
            return {
                "available": False,
                "content": "",
                "source": PROFILE_SOURCE,
                "error": str(exc) or exc.__class__.__name__,
            }
        if not isinstance(profile_context, dict):
            return {
                "available": False,
                "content": "",
                "source": PROFILE_SOURCE,
                "error": "profile provider returned non-dict result",
            }
        return {
            "available": bool(profile_context.get("available", False)),
            "content": str(profile_context.get("content") or ""),
            "source": str(profile_context.get("source") or PROFILE_SOURCE),
            "error": str(profile_context.get("error") or ""),
        }

    async def _analyze_query(
        self,
        role_id: str,
        query_text: str,
        current_time: Any,
        user_profile: str,
        target_object: str,
        request_cache: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        cache_key = self._analysis_cache_key(role_id, query_text, current_time, user_profile, target_object)
        if request_cache is not None:
            analysis_cache = request_cache.setdefault("analysis", {})
            if cache_key in analysis_cache:
                return copy.deepcopy(analysis_cache[cache_key])
        analyze = self.analyzer.analyze
        kwargs: Dict[str, Any] = {}
        if self._supports_keyword_parameter(analyze, "user_profile"):
            kwargs["user_profile"] = user_profile
        if self._supports_keyword_parameter(analyze, "target_object"):
            kwargs["target_object"] = target_object
        result = await analyze(
            role_id=role_id,
            query_text=query_text,
            current_time=current_time,
            **kwargs,
        )
        if request_cache is not None:
            request_cache.setdefault("analysis", {})[cache_key] = copy.deepcopy(result)
        return result

    def _build_prompt_context(
        self,
        query_text: str,
        sub_queries: List[Dict[str, Any]],
        evidence_items: List[EvidenceItem],
        max_items: int,
        user_profile: str,
    ) -> str:
        build = self.prompt_builder.build
        if self._supports_keyword_parameter(build, "user_profile"):
            return build(
                query_text=query_text,
                sub_queries=sub_queries,
                evidence_items=evidence_items,
                max_items=max_items,
                user_profile=user_profile,
            )
        return build(
            query_text=query_text,
            sub_queries=sub_queries,
            evidence_items=evidence_items,
            max_items=max_items,
        )

    @staticmethod
    def _supports_keyword_parameter(func: Any, parameter_name: str) -> bool:
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):
            return True
        for parameter in signature.parameters.values():
            if parameter.kind == inspect.Parameter.VAR_KEYWORD:
                return True
        parameter = signature.parameters.get(parameter_name)
        return parameter is not None and parameter.kind != inspect.Parameter.POSITIONAL_ONLY

    async def _embed_once(self, text: str, request_cache: Optional[Dict[str, Any]] = None) -> Optional[List[float]]:
        cache_key = str(text or "")
        if request_cache is not None:
            embeddings = request_cache.setdefault("embeddings", {})
            if cache_key in embeddings:
                return embeddings[cache_key]
            embedding_tasks = request_cache.setdefault("embedding_tasks", {})
            task = embedding_tasks.get(cache_key)
            if task is None:
                task = asyncio.create_task(self._embed_once_uncached(cache_key))
                embedding_tasks[cache_key] = task
            try:
                result = await task
            finally:
                if task.done():
                    embedding_tasks.pop(cache_key, None)
            embeddings[cache_key] = result
            return result
        return await self._embed_once_uncached(cache_key)

    async def _embed_once_uncached(self, text: str) -> Optional[List[float]]:
        try:
            if self.embedding_client is None:
                from app.common.client.embedding_client import get_embedding_client

                client = get_embedding_client()
            else:
                client = self.embedding_client
            return await client.embed(str(text or ""))
        except Exception as exc:
            logger.warning("Query embedding failed, vector routes may fallback/skip: %s", exc)
            return None

    async def _process_sub_queries(
        self,
        role_id: str,
        query_text: str,
        sub_queries: List[Dict[str, Any]],
        current_time: Any,
        top_k: int,
        request_cache: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        semaphore = asyncio.Semaphore(self.max_sub_query_concurrency)

        async def run_one(index: int, sub_query: Dict[str, Any]) -> Dict[str, Any]:
            async with semaphore:
                return await self._process_sub_query(
                    index=index,
                    role_id=role_id,
                    query_text=query_text,
                    sub_query=sub_query,
                    current_time=current_time,
                    top_k=top_k,
                    request_cache=request_cache,
                )

        results = await asyncio.gather(*(run_one(index, sub_query) for index, sub_query in enumerate(sub_queries)))
        return sorted(results, key=lambda result: result["index"])

    async def _process_sub_query(
        self,
        index: int,
        role_id: str,
        query_text: str,
        sub_query: Dict[str, Any],
        current_time: Any,
        top_k: int,
        request_cache: Dict[str, Any],
    ) -> Dict[str, Any]:
        routes = list(sub_query.get("routes") or ["fact", "relation", "vector"])
        query_embedding = None
        if "fact" in routes or "relation" in routes or "vector" in routes:
            query_embedding = await self._embed_once(
                sub_query.get("query") or query_text,
                request_cache=request_cache,
            )
        route_results = await asyncio.gather(
            self._run_route("fact", index, routes, self.fact_retriever.retrieve, role_id, sub_query, query_embedding, current_time, top_k),
            self._run_route("relation", index, routes, self.relation_retriever.retrieve, role_id, sub_query, query_embedding, current_time, top_k),
            self._run_route("vector", index, routes, self.chunk_retriever.retrieve, role_id, sub_query, query_embedding, current_time, top_k),
        )
        items: List[EvidenceItem] = []
        for route_items in route_results:
            for item in route_items["items"]:
                if item.evidence_type == "derived_fact" or item.dev_uuid:
                    continue
                item.metadata.setdefault("sub_query_index", index)
                item.metadata.setdefault("sub_query_indices", [index])
                item.metadata.setdefault("sub_query", sub_query.get("query"))
                item.metadata.setdefault("sub_query_routes", routes)
                item.metadata.setdefault("time_constraint", sub_query.get("time") or {})
                items.append(item)
        route_diagnostics = [result["trace"] for result in route_results]
        candidate_evidence = [
            candidate
            for result in route_results
            for candidate in result.get("candidate_evidence") or []
        ]
        errors = self._stable_route_errors(
            [
                {"route": result["route"], "sub_query": sub_query.get("query"), **route_error}
                for result in route_results
                for route_error in result["trace"].get("errors") or []
            ]
        )
        return {
            "index": index,
            "items": items,
            "errors": errors,
            "route_diagnostics": route_diagnostics,
            "candidate_evidence": candidate_evidence,
            "trace": {"sub_query_index": index, "sub_query": sub_query.get("query"), "routes": route_diagnostics},
        }

    async def _run_route(
        self,
        route_name: str,
        sub_query_index: int,
        routes: List[str],
        func: Any,
        role_id: str,
        sub_query: Dict[str, Any],
        query_embedding: Optional[List[float]],
        current_time: Any,
        top_k: int,
    ) -> Dict[str, Any]:
        route_trace = new_trace(
            sub_query_index=sub_query_index,
            route=route_name,
            sub_query=str(sub_query.get("query") or ""),
        )
        if route_name not in routes:
            return {"route": route_name, "items": [], "trace": route_trace, "candidate_evidence": []}
        try:
            result: List[EvidenceItem]
            kwargs: Dict[str, Any] = {"query_embedding": query_embedding, "top_k": top_k}
            if route_name == "fact":
                kwargs["current_time"] = current_time
            elif route_name == "vector":
                pass
            else:
                kwargs["current_time"] = current_time
            if self._supports_keyword_parameter(func, "trace"):
                kwargs["trace"] = route_trace
            result = await func(role_id, sub_query, **kwargs)
            if not route_trace["stages"]["route_candidates"]:
                for item in result:
                    trace_record(
                        route_trace,
                        "route_candidates",
                        trace_evidence(item, identity=self._item_identity(item)),
                    )
            candidate_evidence = []
            for rank, item in enumerate(result, start=1):
                candidate_evidence.append(
                    {
                        **self._evidence_trace(item),
                        "sub_query_index": sub_query_index,
                        "route": route_name,
                        "route_rank": rank,
                        "entered_candidate": True,
                        "entered_selected_evidence": False,
                        "_identity": self._item_identity(item),
                    }
                )
            return {
                "route": route_name,
                "items": result,
                "trace": route_trace,
                "candidate_evidence": candidate_evidence,
            }
        except Exception as exc:
            logger.warning("Retrieval route failed: route=%s error=%s", route_name, exc)
            route_trace["errors"].append({"stage": "route", "error": str(exc)})
            return {"route": route_name, "items": [], "trace": route_trace, "candidate_evidence": []}

    @staticmethod
    def _evidence_trace(item: EvidenceItem) -> Dict[str, Any]:
        return {
            "chunk_uuid": item.chunk_uuid,
            "ori_fact_uuid": item.ori_fact_uuid,
            "fact_uuid": item.fact_uuid,
            "source": item.source,
            "valid_time": json_safe(item.valid_time),
            "local_score": item.local_score,
            "final_score": item.final_score,
        }

    def _select_evidence(
        self,
        items: List[EvidenceItem],
        sub_queries: List[Dict[str, Any]],
        top_k: int,
    ) -> List[EvidenceItem]:
        if top_k <= 0:
            return []

        ranked = self._rank_items(items)
        selected: List[EvidenceItem] = []
        selected_ids = set()
        aggregate_indexes = {
            index
            for index, sub_query in enumerate(sub_queries)
            if self._is_aggregate_query(sub_query)
        }

        if aggregate_indexes:
            aggregate_budget = min(top_k, max(3, min(8, top_k // 2 + 2)))
            aggregate_candidates = [
                item
                for item in ranked
                if self._item_sub_query_indexes(item) & aggregate_indexes
            ]

            # Reserve one atomic fact for every aggregate sub-query before
            # sampling rank bands from the shared candidate pool. Merge can
            # collapse the same fact across sub-queries, so membership must be
            # retained independently of the single legacy sub_query_index.
            for sub_index in sorted(aggregate_indexes):
                candidates = [
                    item
                    for item in aggregate_candidates
                    if sub_index in self._item_sub_query_indexes(item)
                ]
                if candidates:
                    self._append_unique(selected, selected_ids, candidates[0])

            active_sources = sorted(
                {
                    source
                    for item in aggregate_candidates
                    for source in (item.sources or [item.source])
                    if source
                }
            )
            for source in active_sources:
                source_candidates = [
                    item
                    for item in aggregate_candidates
                    if item.source == source or source in item.sources
                ]
                for candidate in self._aggregate_rank_band_candidates(
                    source_candidates,
                    source=source,
                    budget=aggregate_budget,
                ):
                    self._append_unique(selected, selected_ids, candidate)
                    if len(selected) >= aggregate_budget or len(selected) >= top_k:
                        break
                if len(selected) >= aggregate_budget or len(selected) >= top_k:
                    break

        for sub_index in range(len(sub_queries)):
            if sub_index in aggregate_indexes:
                continue
            candidates = [
                item for item in ranked
                if sub_index in self._item_sub_query_indexes(item)
            ]
            if candidates:
                self._append_unique(selected, selected_ids, candidates[0])
                if len(selected) >= top_k:
                    break

        if top_k >= 3:
            route_budget = self._route_recall_budget(top_k)
            for source in ("relation", "vector", "fact"):
                candidates = [item for item in ranked if item.source == source or source in item.sources]
                protected = 0
                for item in candidates:
                    if len(selected) >= top_k or protected >= route_budget.get(source, 0):
                        break
                    if self._append_unique(selected, selected_ids, item):
                        protected += 1

        chunk_counts: Dict[str, int] = {}
        source_counts: Dict[str, int] = {}
        for item in selected:
            primary = item.source or (item.sources[0] if item.sources else "")
            source_counts[primary] = source_counts.get(primary, 0) + 1
            if item.chunk_uuid:
                chunk_counts[item.chunk_uuid] = chunk_counts.get(item.chunk_uuid, 0) + 1

        while len(selected) < top_k:
            remaining = [item for item in ranked if self._item_identity(item) not in selected_ids]
            if not remaining:
                break
            item = max(
                remaining,
                key=lambda candidate: (
                    self._diversified_selection_score(candidate, source_counts, chunk_counts, top_k),
                    candidate.final_score,
                    candidate.local_score,
                ),
            )
            if len(selected) >= top_k:
                break
            if item.chunk_uuid:
                count = chunk_counts.get(item.chunk_uuid, 0)
                if count >= 2 and item.source != "relation":
                    selected_ids.add(self._item_identity(item))
                    continue
                chunk_counts[item.chunk_uuid] = count + 1
            if self._append_unique(selected, selected_ids, item):
                primary = item.source or (item.sources[0] if item.sources else "")
                source_counts[primary] = source_counts.get(primary, 0) + 1

        return selected[:top_k]

    @staticmethod
    def _is_aggregate_query(sub_query: Dict[str, Any]) -> bool:
        text = str(sub_query.get("query") or "").strip().lower()
        return bool(
            re.search(r"\bwhat are the names\b", text)
            or re.search(r"\bwhat are\b", text)
            or re.search(r"\bhow many\b", text)
            or re.search(r"\bwhich (?:places|events|books|activities|games|pets)\b", text)
            or re.search(r"\b(list|names of)\b", text)
        )

    @staticmethod
    def _item_sub_query_indexes(item: EvidenceItem) -> set[int]:
        raw_indexes = item.metadata.get("sub_query_indices")
        if not isinstance(raw_indexes, (list, tuple, set)):
            raw_indexes = [item.metadata.get("sub_query_index")]
        indexes: set[int] = set()
        for value in raw_indexes:
            try:
                indexes.add(int(value))
            except (TypeError, ValueError):
                continue
        return indexes

    @staticmethod
    def _route_raw_hit_rank(item: EvidenceItem, source: str) -> int:
        value = (item.metadata.get("route_raw_hit_ranks") or {}).get(source)
        if value in (None, ""):
            value = item.metadata.get("raw_hit_rank")
        try:
            return int(value)
        except (TypeError, ValueError):
            return 10**9

    @staticmethod
    def _route_retrieval_score(item: EvidenceItem, source: str) -> float:
        value = (item.metadata.get("route_retrieval_scores") or {}).get(source)
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _aggregate_rank_band_candidates(
        cls,
        candidates: List[EvidenceItem],
        *,
        source: str,
        budget: int,
    ) -> List[EvidenceItem]:
        if budget <= 0:
            return []
        ranked = sorted(
            candidates,
            key=lambda item: (
                cls._route_raw_hit_rank(item, source),
                -item.final_score,
                -item.local_score,
            ),
        )
        if len(ranked) <= budget:
            return ranked
        bands = [1, 2, 4, 7, 11, 15, 20, 26, 34, 44, 56, 72]
        selected: List[EvidenceItem] = []
        remaining = list(ranked)
        for band in bands:
            if len(selected) >= budget or not remaining:
                break
            candidate = min(
                remaining,
                key=lambda item: (
                    abs(cls._route_raw_hit_rank(item, source) - band),
                    -item.final_score,
                    -item.local_score,
                ),
            )
            selected.append(candidate)
            remaining.remove(candidate)
        return selected

    @staticmethod
    def _rank_items(items: List[EvidenceItem]) -> List[EvidenceItem]:
        return sorted(items, key=lambda item: (item.final_score, item.local_score), reverse=True)

    @staticmethod
    def _route_recall_budget(top_k: int) -> Dict[str, int]:
        if top_k >= 12:
            return {"relation": 2, "vector": 2, "fact": 1}
        if top_k >= 5:
            return {"relation": 1, "vector": 1, "fact": 1}
        return {"relation": 1, "vector": 0, "fact": 1}

    @staticmethod
    def _diversified_selection_score(
        item: EvidenceItem,
        source_counts: Dict[str, int],
        chunk_counts: Dict[str, int],
        top_k: int,
    ) -> float:
        source = item.source or (item.sources[0] if item.sources else "")
        source_count = source_counts.get(source, 0)
        chunk_count = chunk_counts.get(item.chunk_uuid or "", 0)
        diversity_bonus = 0.04 if source_count == 0 else 0.0
        source_penalty = 0.02 * max(source_count - max(1, top_k // 3), 0)
        chunk_penalty = 0.03 * max(chunk_count - 1, 0)
        return item.final_score + diversity_bonus - source_penalty - chunk_penalty

    @staticmethod
    def _item_identity(item: EvidenceItem) -> str:
        if item.ori_fact_uuid:
            return f"ori:{item.ori_fact_uuid}"
        if item.fact_uuid:
            return f"fact:{item.fact_uuid}"
        if item.metadata.get("relation_uuid"):
            return f"relation:{item.metadata.get('relation_uuid')}"
        if item.metadata.get("relation_uuids"):
            return "relation_path:" + "|".join(str(value) for value in item.metadata.get("relation_uuids") or [])
        if item.metadata.get("path_key"):
            return f"path:{item.metadata.get('path_key')}"
        if item.chunk_uuid is not None and item.chunk_content_index is not None:
            return f"chunk:{item.chunk_uuid}:{item.chunk_content_index}"
        if item.chunk_uuid is not None:
            return f"chunk:{item.chunk_uuid}"
        return f"content:{item.content[:80]}"

    def _append_unique(self, selected: List[EvidenceItem], selected_ids: set, item: EvidenceItem) -> bool:
        identity = self._item_identity(item)
        if identity in selected_ids:
            return False
        selected_ids.add(identity)
        selected.append(item)
        return True

    def _get_usage_tracker(self) -> Any:
        if self.fact_repository is not None:
            return self.fact_repository
        if self.fact_store is not None and hasattr(self.fact_store, "touch_original_fact_used"):
            return self.fact_store
        from app.memory.fact_node.fact_graph.fact_repository import FactGraphRepository

        self.fact_repository = FactGraphRepository()
        return self.fact_repository

    async def _mark_selected_used(self, role_id: str, items: List[EvidenceItem], used_time: Any) -> None:
        if not self.mark_used:
            return
        if self.mark_used_mode == "sync":
            await self._mark_used(role_id, items, used_time)
            return
        self._schedule_mark_used(role_id, items, used_time)

    def _schedule_mark_used(self, role_id: str, items: List[EvidenceItem], used_time: Any) -> None:
        task = asyncio.create_task(self._mark_used_background(role_id, list(items), used_time))
        self._mark_used_tasks.add(task)
        task.add_done_callback(self._mark_used_tasks.discard)

    async def _mark_used_background(self, role_id: str, items: List[EvidenceItem], used_time: Any) -> None:
        try:
            await self._mark_used(role_id, items, used_time)
        except asyncio.CancelledError:
            logger.debug("background mark_used task cancelled")
            raise
        except Exception as exc:
            logger.warning("background mark_used failed: %s", exc)

    async def drain_mark_used_tasks(self) -> None:
        if not self._mark_used_tasks:
            return
        await asyncio.gather(*list(self._mark_used_tasks), return_exceptions=True)

    async def _mark_used(self, role_id: str, items: List[EvidenceItem], used_time: Any) -> None:
        original_ids = []
        for item in items:
            if item.ori_fact_uuid:
                original_ids.append(item.ori_fact_uuid)
        if not original_ids:
            return
        try:
            usage_tracker = self._get_usage_tracker()
        except Exception as exc:
            logger.warning("get usage tracker failed: %s", exc)
            return
        for ori_fact_uuid in dict.fromkeys(original_ids):
            try:
                await usage_tracker.touch_original_fact_used(role_id, ori_fact_uuid, used_time)
            except Exception as exc:
                logger.warning("touch original fact used failed: %s", exc)

    @staticmethod
    def _normalize_mark_used_mode(value: str) -> str:
        mode = str(value or "background").strip().lower()
        if mode in {"background", "async"}:
            return "background"
        if mode == "sync":
            return "sync"
        raise ValueError("mark_used_mode must be 'background' or 'sync'")

    @staticmethod
    def _new_request_cache() -> Dict[str, Any]:
        return {"analysis": {}, "embeddings": {}, "embedding_tasks": {}}

    @staticmethod
    def _analysis_cache_key(
        role_id: str,
        query_text: str,
        current_time: Any,
        user_profile: str,
        target_object: str,
    ) -> tuple[str, str, str, str, str]:
        if isinstance(current_time, datetime):
            current_time_key = current_time.isoformat()
        else:
            current_time_key = str(current_time or "")
        profile_hash = hashlib.sha256(str(user_profile or "").encode("utf-8")).hexdigest()
        return (str(role_id or ""), str(query_text or ""), current_time_key, profile_hash, str(target_object or ""))

    @staticmethod
    def _stable_route_errors(errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        route_order = {"fact": 0, "relation": 1, "vector": 2}
        return sorted(errors, key=lambda error: route_order.get(str(error.get("route") or ""), 99))
