"""fact_node 的 LLM 调用适配层。

这里不直接写 Neo4j / Milvus，只负责把 pipeline 的输入转换成 prompt，
再把模型输出解析成 schema.py 中的中间结构。
"""

import json
import logging
from typing import Any, Dict, List, Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.common.client.llm_client import get_llm_client
from app.memory.fact_node.fact_graph.schema import (
    ALLOWED_ENTITY_TYPES,
    EntityItem,
    ProfileUpdateDecision,
)
from app.memory.fact_node.prompt.extract_prompt_update import (
    SYSTEM_PROMPT,
    DEV_IF_PREFERENCE_PROMPT,
    DEV_SUMMARY_MERGE_PROMPT,
    ORI_TOPIC_IF_PROFILE_PROMPT,
    TopicCheck,
    PROFILE_UPDATE_PROMPT,
    PROFILECheck,
    ENTITY_PROMPT,
    EntityCheck,
)

logger = logging.getLogger(__name__)
_JSONModel = TypeVar("_JSONModel", bound=BaseModel)


class FactLLMExtractor:
    """集中管理 fact_node 使用的 prompt 和返回解析。"""

    async def _chat_json_with_retry(
        self,
        prompt: str,
        check_model: Type[_JSONModel],
        *,
        max_retries: int = 3,
        expect_list: bool = False,
        unwrap_key: str | None = None,
        json_mode: bool = True,
        temperature: float = 0.1,
    ) -> Any | None:
        client = await get_llm_client()

        for retry in range(max_retries):
            response = await client.chat(
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
                json_mode=json_mode,
                temperature=temperature,
                max_retries=1,
            )

            payload = response.content

            if payload in ({}, None, ""):
                logger.warning("LLM JSON 输出为空，第 %s 次重试", retry + 1)
                continue

            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    logger.warning("LLM JSON 解析失败，第 %s 次重试: %s", retry + 1, payload[:200])
                    continue

            if unwrap_key and isinstance(payload, dict):
                payload = payload.get(unwrap_key, [])

            if expect_list:
                if not isinstance(payload, list):
                    logger.warning("LLM JSON 输出不是 list，第 %s 次重试: %s", retry + 1, type(payload).__name__)
                    continue

                try:
                    for item in payload:
                        check_model.model_validate(item)
                except ValidationError as e:
                    logger.warning("LLM JSON list 元素格式错误，第 %s 次重试", retry + 1)
                    logger.warning("%s", e)
                    continue

                return payload

            if not isinstance(payload, dict):
                logger.warning("LLM JSON 输出不是 dict，第 %s 次重试: %s", retry + 1, type(payload).__name__)
                continue

            try:
                check_model.model_validate(payload)
            except ValidationError as e:
                logger.warning("LLM JSON 格式错误，第 %s 次重试", retry + 1)
                logger.warning("%s", e)
                continue

            return payload

        logger.error("LLM 连续 %s 次 JSON 输出校验失败，跳过本次处理", max_retries)
        return None


    async def detect_dev(
        self,
        chunk_summary,
        target_object: str = "",
        max_retries: int = 5,
    ) -> str:
        """使用 DEV_IF_PREFERENCE_PROMPT 生成派生事实候选。

        返回空字符串表示该 summary 不适合产生 DerivedFact。
        max_retries 会继续传给底层 LLMClient.chat。
        """
        client = await get_llm_client()

        prompt = DEV_IF_PREFERENCE_PROMPT.format(
            chunk_summary=chunk_summary,
            target_object=target_object or "The target object",
        )

        response = await client.chat(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
            json_mode=False,
            temperature=0.1,
            max_retries=max_retries,
        )

        return (response.content or "").strip()

    async def merge_dev_summary(
        self,
        old_dev_summary: str,
        new_dev_summary: str,
        max_retries: int = 3,
    ) -> str:
        """使用 DEV_SUMMARY_MERGE_PROMPT 合并新旧 DerivedFact summary。"""
        client = await get_llm_client()

        prompt = DEV_SUMMARY_MERGE_PROMPT.format(
            old_summary=old_dev_summary or "",
            new_summary=new_dev_summary,
        )

        response = await client.chat(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
            json_mode=False,
            temperature=0.1,
            max_retries=max_retries,
        )

        return (response.content or "").strip()

    async def extract_profile_update(
        self,
        old_profile: dict,
        summary: str,
        target_object: str = "",
        max_retries: int = 3,
    ) -> ProfileUpdateDecision:
        """使用 PROFILE_UPDATE_PROMPT 判断 summary 是否写入用户画像。"""
        client = await get_llm_client()

        prompt = PROFILE_UPDATE_PROMPT.format(
            old_profile=json.dumps(old_profile, ensure_ascii=False),
            summary=summary,
            target_object=target_object or "The target object",
        )

        payload = await self._chat_json_with_retry(
            prompt,
            PROFILECheck,
            max_retries=max_retries,
            json_mode=True,
        )

        return self._parse_profile_update_payload(payload or {})

    # 提取 summary list 的实体
    async def extract_entities_from_summaries(
        self,
        chunk_summaries: list,
        max_retries: int = 3,
    ) -> List[EntityItem]:
        """使用 ENTITY_PROMPT 从 chunk summaries 中抽取实体候选。

        模型可能返回 list、JSON 字符串或 {"entities": [...]}，
        这里统一解析成 List[EntityItem]。
        """
        client = await get_llm_client()

        prompt = ENTITY_PROMPT.format(
            chunk_summary=json.dumps(chunk_summaries, ensure_ascii=False),
        )

        items = await self._chat_json_with_retry(
            prompt,
            EntityCheck,
            max_retries=max_retries,
            expect_list=True,
            unwrap_key="entities",
            json_mode=False,
        )

        if not isinstance(items, list):
            return []

        entities: List[EntityItem] = []
        for item in items:
            name = str((item or {}).get("entity_name", "")).strip()
            entity_type = str((item or {}).get("entity_type", "")).strip()
            semantic = str((item or {}).get("entity_semantic", "")).strip()
            if name and entity_type in ALLOWED_ENTITY_TYPES:
                entities.append(EntityItem(name=name, type=entity_type, semantic=semantic))

        return entities

    # 提取单个summary 实体
    async def extract_entity_from_summary(
            self,
            chunk_summary:str,
            max_retries: int = 3,
    ) -> List[dict] | None:
        """使用 DEV_SUMMARY_MERGE_PROMPT 合并新旧 DerivedFact summary。"""
        client = await get_llm_client()

        prompt = ENTITY_PROMPT.format(
            chunk_summary=chunk_summary
        )

        entities = await self._chat_json_with_retry(
            prompt,
            EntityCheck,
            max_retries=max_retries,
            expect_list=True,
            unwrap_key="entities",
            json_mode=False,
        )

        if not isinstance(entities, list):
            return None

        return entities

    async def extract_ori_fact_summary(
        self,
        existing_ori_summary: str,
        new_summary: str,
        target_object: str = "",
        max_retries: int = 3,
    ) -> dict:
        """使用 ORI_TOPIC_IF_PROFILE_PROMPT 生成 OriginalFact topic 和 profile_update。"""
        client = await get_llm_client()
        prompt = ORI_TOPIC_IF_PROFILE_PROMPT.format(
            old_summary=existing_ori_summary or "",
            new_summary=new_summary,
            target_object=target_object or "The target object",
        )
        payload = await self._chat_json_with_retry(
            prompt,
            TopicCheck,
            max_retries=max_retries,
            json_mode=True,
        )

        return payload or {}

    @staticmethod
    def _parse_profile_update_payload(payload: dict) -> ProfileUpdateDecision:
        """解析 PROFILE_UPDATE_PROMPT 输出的画像字段。"""
        allowed_fields = ("basic_info", "preference", "skill")
        updates: Dict[str, str] = {}

        for key in allowed_fields:
            value = str(payload.get(key, "")).strip()
            if value:
                updates[key] = value

        return ProfileUpdateDecision(
            should_update=bool(updates),
            updates=updates,
            reason="",
        )
