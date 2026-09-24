"""OriginalFact evidence content provider."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Iterable, List


CONTENT_ORIGIN = "fact_store.get_original_fact_summary"
logger = logging.getLogger(__name__)


def flatten_summary_texts(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        texts: List[str] = []
        for item in value:
            texts.extend(flatten_summary_texts(item))
        return texts
    text = str(value).strip()
    return [text] if text else []


async def get_many_for_role(source_provider: Any, ori_fact_uuids: Iterable[str], role_id: str) -> Dict[str, str]:
    """Call custom providers compatibly while enforcing role-aware production reads."""

    method = getattr(source_provider, "get_many")
    try:
        import inspect

        parameters = inspect.signature(method).parameters
        supports_role = "role_id" in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
        )
    except (TypeError, ValueError):
        supports_role = False
    if supports_role:
        return await method(ori_fact_uuids, role_id=role_id)
    return await method(ori_fact_uuids)


class OriginalFactSourceProvider:
    def __init__(self, fact_store=None):
        if fact_store is None:
            from app.memory.fact_node.fact_graph.fact_store import FactStore

            fact_store = FactStore()
        self.fact_store = fact_store

    async def get_content(self, ori_fact_uuid: str, role_id: str | None = None) -> str:
        if not ori_fact_uuid:
            return ""
        if role_id and getattr(self.fact_store, "manager", None) is not None:
            text = await self._get_original_fact_summary_from_manager(ori_fact_uuid, role_id=role_id)
            return " ".join(flatten_summary_texts(text)).strip()
        try:
            text = await self.fact_store.get_original_fact_summary(ori_fact_uuid)
        except TypeError as exc:
            if "expected str instance, list found" not in str(exc):
                raise
            text = await self._get_original_fact_summary_from_manager(ori_fact_uuid, role_id=role_id)
        return " ".join(flatten_summary_texts(text)).strip()

    async def get_many(self, ori_fact_uuids: Iterable[str], role_id: str | None = None) -> Dict[str, str]:
        ids = list(dict.fromkeys(str(value) for value in ori_fact_uuids if value))
        if not ids:
            return {}
        batch_values = await self._get_many_from_manager(ids, role_id=role_id)
        if batch_values is not None:
            return {ori_fact_uuid: batch_values.get(ori_fact_uuid, "") for ori_fact_uuid in ids}
        values = await asyncio.gather(*(self.get_content(value, role_id=role_id) for value in ids))
        return {ori_fact_uuid: content for ori_fact_uuid, content in zip(ids, values)}

    async def _get_many_from_manager(
        self,
        ori_fact_uuids: List[str],
        role_id: str | None = None,
    ) -> Dict[str, str] | None:
        manager = getattr(self.fact_store, "manager", None)
        if manager is None or not hasattr(manager, "execute_query"):
            return None
        rows = await self._execute_batch_summary_query(manager, ori_fact_uuids, role_id=role_id)
        if rows is None:
            return None
        result: Dict[str, str] = {}
        for row in rows or []:
            ori_fact_uuid = row.get("ori_fact_uuid")
            if not ori_fact_uuid:
                continue
            result[str(ori_fact_uuid)] = " ".join(flatten_summary_texts(row.get("summaries", []))).strip()
        return result

    async def _execute_batch_summary_query(
        self,
        manager: Any,
        ori_fact_uuids: List[str],
        role_id: str | None = None,
    ) -> List[Dict[str, Any]] | None:
        role_filter = "WHERE o.role_id = $role_id" if role_id else ""
        chunk_role_filter = "WHERE c IS NULL OR c.role_id = $role_id" if role_id else ""
        params = {"ori_fact_uuids": ori_fact_uuids}
        if role_id:
            params["role_id"] = role_id
        try:
            return await manager.execute_query(
                f"""
                UNWIND $ori_fact_uuids AS ori_fact_uuid
                MATCH (o:OriginalFact {{ori_fact_uuid: ori_fact_uuid}})
                {role_filter}
                OPTIONAL MATCH (c:ChunkNode)-[:HAS_FACT]->(o)
                {chunk_role_filter}
                WITH ori_fact_uuid, c
                ORDER BY c.valid_time ASC, c.chunk_uuid ASC
                WITH ori_fact_uuid, collect(c.summary) AS summaries
                RETURN ori_fact_uuid, summaries
                """,
                params,
            )
        except Exception as exc:
            logger.debug("batch original fact summary lookup failed, falling back to per-id calls: %s", exc)
            return None

    async def _get_original_fact_summary_from_manager(
        self,
        ori_fact_uuid: str,
        role_id: str | None = None,
    ) -> str:
        manager = getattr(self.fact_store, "manager", None)
        if manager is None or not hasattr(manager, "execute_query"):
            return ""
        role_filter = "WHERE o.role_id = $role_id" if role_id else ""
        params = {"ori_fact_uuid": ori_fact_uuid}
        if role_id:
            params["role_id"] = role_id
        rows = await manager.execute_query(
            f"""
            MATCH (o:OriginalFact {{ori_fact_uuid: $ori_fact_uuid}})
            {role_filter}
            MATCH (c:ChunkNode)-[:HAS_FACT]->(o)
            ORDER BY c.valid_time ASC, c.chunk_uuid ASC
            WITH c.summary AS summary
            WHERE summary IS NOT NULL
            RETURN collect(summary) AS summaries
            """,
            params,
        )
        if not rows:
            return ""
        return " ".join(flatten_summary_texts(rows[0].get("summaries", []))).strip()
