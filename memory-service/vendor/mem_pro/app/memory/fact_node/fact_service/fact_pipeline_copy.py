"""
该文件重塑 fact 层的构建
解耦
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Set, Tuple, Optional, Literal
from app.memory.chunk_node.chunk_graph.chunk_store import ChunkStore
from app.DBserver.milvus_repository.milvus_operate import MilvusCRUD
from app.memory.fact_node.fact_service.llm_extractor import FactLLMExtractor
from app.memory.fact_node.fact_graph.fact_store import FactStore
from app.common.client.embedding_client import get_embedding_client
from app.extra_user_profile.important_event import UserProfile
from app.retrieval.milvus_search import quote_expr_value
import app.common.config.parameters_config as config
# from app.memory.fact_node.fact_graph.rules import (
#     build_derived_fact_ddl,
#     content_contains_entity,
#     decide_derived_fact_status
# )
from app.memory.fact_node.fact_graph.schema import (
    EntityItem,
#     DerivedFactCandidate,
#     ExtractResult,
#     OriginalFactCandidate,
)

logger = logging.getLogger(__name__)

class BuildOriFact:
    def __init__(self):
        self.chunk_store = ChunkStore()
        self.milvus_crud = MilvusCRUD()
        self.llm_extractor = FactLLMExtractor()
        self.fact_store = FactStore()
        self.user_profile_event = UserProfile()

    """
    ============== 构建 ori_fact 相关 =================
    1. 获取 chunk_uuid -> chunk_summary
    2. 获取 chunk_embedding 向量
    3. 在 ori_fact_schema 中进行向量匹配 取 top1, 要求 top1.distance < w2
    4. 若匹配成功，获取 已存在 ori_fact_uuid, ori_fact_summary
    5. 扔进大模型 ORI_TOPIC_IF_PROFILE_PROMPT -> topic: 生成新的 summary
                                             -> profile: 是否涉及用户画像相关
    """

    # 从 milvus 中获取 chunk_summary, chunk_embedding
    # return chunk_summary, chunk_embedding
    async def get_chunk_summary_embedding(
            self,
            chunk_uuid: str
    ) -> Optional[tuple[str, List]]:
        # 从neo4j节点获取 chunk_summary
        chunk_summary = await self.chunk_store.get_chunk_summary_by_uuid(
            chunk_uuid
        )
        # 从milvus获取 chunk_embedding
        chunk_embedding = await self.milvus_crud.query(
            collection_name="chunk_schema",
            expr=f"chunk_uuid == {quote_expr_value(chunk_uuid)}",
            output_fields=["summary_embedding"],
        )

        return chunk_summary, chunk_embedding[0]["summary_embedding"]

    # 获取的 chunk_embedding 与 ori_embedding 进行向量匹配
    # return ori_fact_uuid, ori_fact_summary
    # return None
    async def chunk_match_ori_fact(
            self,
            role_id: str,
            chunk_embedding: list
    ) -> dict | None:
        return await self.milvus_crud.search_top(
            collection_name="ori_fact_schema",
            embedding=list(chunk_embedding),
            top_k=1,
            expr=f"role_id == {quote_expr_value(role_id)}",
            vector_field="summary_embedding",
        )


    # ======== Step 4-1 可复用已存在 ori_fact 合并 =========
    # 1. 更新 ori_fact 中
    #    summary (topic)
    #    confidence
    # 2. 新 summary (topic) 转换成向量
    # 3，summary (topic) 和 summary_embedding 更新于 milvus 中存储
    # 4. 将该 ori_fact_uuid 写入 对应 chunk_uuid milvus 中
    async def merge_chunk_to_ori_fact(
            self,
            ori_fact_uuid: str,
            chunk_uuid: str,
            # chunk_summary: str,
            topic: str
    ):
        # 从节点获取 original_fact 原始 confidence 数值  content 字段
        result = await self.fact_store.get_ori_fact_by_uuid(
            ori_fact_uuid,
            ["confidence"]
        )
        confidence = result["confidence"]
        # content = result["content"]

        # 更新 confidence summary content 字段
        await self.fact_store.update_original_fact(
            chunk_uuid=chunk_uuid,
            ori_fact_uuid=ori_fact_uuid,
            confidence=confidence+1,
            # content=content + chunk_summary,
            last_update_time=datetime.now(),
            summary=topic,
        )

        # 向量化 topic 并存入milvus
        client = get_embedding_client()
        embedding = await client.embed(topic)

        self.milvus_crud.update_(
            collection_name="ori_fact_schema",
            expr=f"uuid == {quote_expr_value(ori_fact_uuid)}",
            updates={
                "summary": topic,
                "summary_embedding": embedding,
            },
        )

        # 将该 ori_fact_uuid 写入 对应 chunk_uuid milvus 中
        self.milvus_crud.update_(
            collection_name="chunk_schema",
            expr=f"chunk_uuid == {quote_expr_value(chunk_uuid)}",
            updates={
                "fact_uuid": ori_fact_uuid,
            },
        )
        return

        # ======== Step 4-2 无可复用，创建 ori_fact =========
        # 1. 获取该事件的重要程度
        # 2. 创建ori_fact 节点
        # 3. 将新的节点信息写进 milvus

    async def create_ori_fact_(
            self,
            chunk_uuid: str,
            role_id: str,
            # chunk_summary: str,
            topic: str,
    ):
        # 获取该事件重要程度
        important_score = await self.user_profile_event.get_importance_score(
            topic
        )

        # 创建 ori_fact 节点
        ori_fact_uuid = await self.fact_store.create_original_fact(
            chunk_uuid=chunk_uuid,
            role_id=role_id,
            # content=chunk_summary,
            summary=topic,  # LLM 生成的 topic 摘要（Milvus 向量化用）
            importance=important_score
        )

        # 向量化 topic 并存入milvus
        client = get_embedding_client()
        embedding = await client.embed(topic)

        # 将新节点信息存入 milvus 中
        data = {
            "role_id": role_id,
            "uuid": ori_fact_uuid,
            "summary": topic,
            "summary_embedding": embedding,
        }
        await self.milvus_crud.insert(
            collection_name="ori_fact_schema",
            data=data,
        )

        # 将该 ori_fact_uuid 写入 对应 chunk_uuid milvus 中
        self.milvus_crud.update_(
            collection_name="chunk_schema",
            expr=f"chunk_uuid == {quote_expr_value(chunk_uuid)}",
            updates={
                "fact_uuid": ori_fact_uuid,
            },
        )



class BuildDevFact:
    def __init__(self):
        self.chunk_store = ChunkStore()
        self.milvus_crud = MilvusCRUD()
        self.llm_extractor = FactLLMExtractor()
        self.fact_store = FactStore()
        self.user_profile_event = UserProfile()

    # 1. chunk_summary llm 判断是否有派生
    # 2. 无派生 return None
    #    有派生 1. chunk_summary 与 dev_summary 向量匹配 -> old_dev_summary, dev_fact_uuid
    #          2. 生成 dev topic
    #             有匹配 old_dev，复用
    #             无匹配 创建
    # llm 判断是否有派生
    # return dev_topic / None
    async def get_dev_topic_from_chunk(
            self,
            chunk_summary: str,
            target_object: str = "",
    ) -> str | None:
        result = await self.llm_extractor.detect_dev(
            chunk_summary,
            target_object=target_object,
        )
        if result == "":
            return None
        return result

    # ============== Step 2 dev_topic 转换成向量与 dev_fact_schema 进行向量匹配 =========================
    # return uuid/ return None
    async def dev_summary_match_dev_fact (
            self,
            role_id: str,
            dev_topic: str,
    ) -> dict | None:
        # 向量化 topic 并存入milvus
        client = get_embedding_client()
        dev_embedding = await client.embed(dev_topic)

        # 去 dev_fact_schema 中进行向量匹配
        return await self.milvus_crud.search_top(
            collection_name="dev_fact_schema",
            embedding=list(dev_embedding),
            top_k=1,
            expr=f"role_id == {quote_expr_value(role_id)}",
            vector_field="summary_embedding",
        )


    # ============== Step 3-1 复用已存在 dev_fact 节点 ===================
    # 当 status = 0 的情况下的节点更新
    # 直接判断是否需要画像更新
    # return topic / None
    async def merge_chunk_to_dev_fact(
            self,
            dev_uuid: str,
            chunk_uuid: str,
            topic: str,
            confidence: int,
    ):
        # 若 confidence 达到稳定临界值
        if confidence >= config.DEV_CONFIDENCE:
            status = 1  # 稳定
            ddl = datetime.now()  # 可以作为 "什么时候变稳定" 的时间截点
        else:
            status = 0  # 不稳定
            ddl = datetime.now() + timedelta(days=90)

        # 更新节点中 confidence summary 字段
        await self.fact_store.update_derived_fact(
            chunk_uuid=chunk_uuid,
            dev_uuid=dev_uuid,
            confidence=confidence,
            summary=topic,
            last_update_time=datetime.now(),
            status=status,
            ddl=ddl
        )

        # 向量化 topic 并存入milvus
        client = get_embedding_client()
        embedding = await client.embed(topic)

        self.milvus_crud.update_(
            collection_name="dev_fact_schema",
            expr=f"uuid == {quote_expr_value(dev_uuid)}",
            updates={
                "summary": topic,
                "summary_embedding": embedding,
            },
        )

        if status == 1:
            return topic
        else:
            return None


    # ============= Step 2-2 创建新的 dev_fact 节点 =====================
    async def create_dev_fact_milvus(
            self,
            chunk_uuid: str,
            role_id: str,
            topic: str
    ):
        # 创建 ori_fact 节点
        dev_uuid = await self.fact_store.create_derived_fact(
            chunk_uuid=chunk_uuid,
            role_id=role_id,
            summary=topic,  # LLM 生成的 topic 摘要（Milvus 向量化用）
        )

        # 向量化 topic 并存入milvus
        client = get_embedding_client()
        embedding = await client.embed(topic)

        # 将新节点信息存入 milvus 中
        data = {
            "role_id": role_id,
            "uuid": dev_uuid,
            "summary": topic,
            "summary_embedding": embedding,
        }
        await self.milvus_crud.insert(
            collection_name="dev_fact_schema",
            data=data,
        )


    async def delete_expired_node(
            self,
    ):
        # 删除 neo4j 中节点
        dev_uuids = await self.fact_store.delete_expired_derived_facts_by_status(
            now_time=datetime.now()
        )

        # 删除 milvus 中对应节点信息
        for dev_uuid in dev_uuids:
            self.milvus_crud.delete(
                collection_name="dev_fact_schema",
                expr=f"uuid == {quote_expr_value(dev_uuid)}",
            )


class BuildEntity:
    def __init__(self):
        self.chunk_store = ChunkStore()
        self.milvus_crud = MilvusCRUD()
        self.llm_extractor = FactLLMExtractor()
        self.fact_store = FactStore()
        self.user_profile_event = UserProfile()
        self.embedding_client = get_embedding_client()

    # 新 semantic_embedding 与数据库中已存在的 semantic_embedding 进行向量匹配
    # return entity_uuid, ori_fact_summary
    # return None
    async def semantic_match_entity(
            self,
            role_id: str,
            entity_name: str,
            entity_type: str,
            semantic_embedding: list
    ) -> dict | None:
        return await self.milvus_crud.search_top(
            collection_name="SemanticEntity",
            embedding=list(semantic_embedding),
            top_k=1,
            expr=(
                f"role_id == {quote_expr_value(role_id)} "
                f"and name == {quote_expr_value(entity_name)} "
                f"and type == {quote_expr_value(entity_type)}"
            ),
            vector_field="semantic_embedding"
        )

    # 实体节点 向量匹配 通过 role_id, entity_name, entity_type 去匹配 entity_semantic
    # 将 llm 输出的实体信息 entity_semantic 向量化
    # 创建/复用 实体节点
    # milvus 存储
    # 输出该轮所有entity节点uuid
    async def entity_embed_save(
            self,
            role_id: str,
            chunk_uuid: str,
            llm_result: list[EntityItem],
    ) -> list[str]:
        entity_uuids = []
        # print("集体向量化")
        entity_semantic_list = []
        for entity in llm_result:
            if entity.type != "Time":
                entity_semantic_list.append(entity.semantic)

        # 集体向量化
        llm_embedding_list = await self.embedding_client.embed_batch(
            entity_semantic_list
        )

        # print("Step 2 对向量化的semantic执行匹配")
        for entity in llm_result:
            entity_name = entity.name
            entity_type = entity.type
            entity_semantic = entity.semantic
            if entity.type != "Time":
                semantic_embed = llm_embedding_list[0]

                # print("开始向量匹配")
                # print("semantic_embed: ", semantic_embed)

                # milvus 向量匹配
                milvus_search = await self.milvus_crud.search_top(
                    collection_name="SemanticEntity",
                    embedding=list(semantic_embed),
                    top_k=1,
                    expr=(
                        f"role_id == {quote_expr_value(role_id)} "
                        f"and name == {quote_expr_value(entity_name)} "
                        f"and type == {quote_expr_value(entity_type)}"
                    ),
                    vector_field="semantic_embedding"
                )

                # print("匹配成功")

                # 匹配成功
                if milvus_search:
                    entity_uuid = milvus_search["uuid"]
                    # 连接 entity - chunk_node
                    await self.fact_store.link_entity_to_chunk_(
                        role_id=role_id,
                        chunk_uuid=chunk_uuid,
                        entity_uuid=entity_uuid,
                    )
                # 未有匹配节点
                else:
                    # 创建新的 entity 节点
                    entity_uuid = await self.fact_store.create_entity_(
                        role_id=role_id,
                        chunk_uuid=chunk_uuid,  # 关联的原始事实 UUID（必传，作为关系定位依据）
                        name=entity_name,  # 实体名，如"北京"
                        entity_type=entity_type,  # 实体类型，如"地点"（5种中文类型之一）
                        semantic=entity_semantic,  # 实体语义补充，如"地点-常去"
                    )

                    # 在 milvus 中存储该节点的信息
                    data = {
                        "uuid": entity_uuid,
                        "role_id": role_id,
                        "name": entity_name,
                        "type": entity_type,
                        "semantic": entity_semantic,
                        "semantic_embedding": semantic_embed
                    }
                    await self.milvus_crud.insert(
                        collection_name="SemanticEntity",
                        data=data,
                    )

                # entity_uuids.append(entity_uuid)
                llm_embedding_list.pop(0)
            # 若 entity_type==Time，直接生成节点，不进milvus和任何向量化
            else:
                entity_uuid = await self.fact_store.create_entity_(
                    role_id=role_id,
                    chunk_uuid=chunk_uuid,  # 关联的原始事实 UUID（必传，作为关系定位依据）
                    name=entity_name,  # 实体名，如"北京"
                    entity_type=entity_type,  # 实体类型，如"地点"（5种中文类型之一）
                    semantic=entity_semantic,  # 实体语义补充，如"地点-常去"
                )
            entity_uuids.append(entity_uuid)

        return entity_uuids







