from app.DBserver.milvus_repository.milvus_operate import MilvusCRUD
from app.memory.fact_node.fact_service.fact_pipeline_copy import (
    BuildOriFact,
    BuildDevFact,
    BuildEntity,
)
from app.memory.fact_node.fact_graph.fact_store import FactStore
# from typing import Any, Dict, List, Set, Tuple, Optional
from app.memory.user_info_node.user_info_graph.user_info_store import UserInfoStore
from app.memory.fact_node.fact_service.llm_extractor import FactLLMExtractor


class FPMain:
    def __init__(self):
        self.build_ori_fact = BuildOriFact()
        self.build_dev_fact = BuildDevFact()
        self.build_entity = BuildEntity()
        self.milvus_crud = MilvusCRUD()
        self.llm_extractor = FactLLMExtractor()
        self.fact_store = FactStore()
        self.user_info_store = UserInfoStore()

    async def build_ori_fact_main(
            self,
            role_id: str,
            chunk_uuid: str,
            chunk_summary: str,
            chunk_embedding: list[float],
            target_object: str = "",
    ) -> str | None:
        # ======== Step 2 与ori_fact进行向量匹配 获取 ori_summary ===============
        result = await self.build_ori_fact.chunk_match_ori_fact(role_id, chunk_embedding)
        print("chunk_match_ori_fact result: ", result)

        # 匹配成功
        if result:
            payload = result.get("payload") or {}
            ori_fact_uuid = result.get("uuid") or payload.get("uuid")
            ori_fact_summary = payload.get("summary", "")
        # 匹配失败
        else:
            ori_fact_uuid = None
            ori_fact_summary = ""

        # ======== Step 3 扔大模型分析 融合生成 topic ==========
        llm_topic_result = await self.llm_extractor.extract_ori_fact_summary(
            ori_fact_summary,
            chunk_summary,
            target_object=target_object,
        )
        if not llm_topic_result:
            return None

        topic_summary = llm_topic_result.get("topic", "")
        profile_update = llm_topic_result.get("profile_update", 0)

        if not topic_summary:
            return None

        # print("llm_topic_result: ", topic, profile_update)

        # ======== Step 4-1 可复用已存在 ori_fact 合并 =========
        if ori_fact_uuid:
            await self.build_ori_fact.merge_chunk_to_ori_fact(
                ori_fact_uuid,
                chunk_uuid,
                # chunk_summary,
                topic_summary,
            )
        # ======== Step 4-2 无可复用，创建 ori_fact =========
        else:
            await self.build_ori_fact.create_ori_fact_(
                chunk_uuid=chunk_uuid,
                role_id=role_id,
                # chunk_summary=chunk_summary,
                topic=topic_summary,
            )

        # 判断是否有用户画像更新相关
        # 若有：则输出 chunk summary, 为之后用户画像 llm 分析留活口
        if profile_update == 1:
            return chunk_summary
        else:
            return None


    async def build_dev_fact_main(
            self,
            role_id: str,
            chunk_uuid: str,
            chunk_summary: str,
            target_object: str = "",
    ) -> str | None:
        # llm 判断是否有派生 有派生：dev_topic = str
        dev_topic = await self.build_dev_fact.get_dev_topic_from_chunk(
            chunk_summary,
            target_object=target_object,
        )

        # 有派生  return dev_topic 为之后用户画像留活口
        # 否则 return None
        if dev_topic:
            # 向量匹配  uuid  None
            result = await self.build_dev_fact.dev_summary_match_dev_fact(
                role_id,
                dev_topic
            )
            # 匹配成功 复用
            if result:
                dev_uuid = result["uuid"]
                # print("matched dev_uuid: ", dev_uuid)
                # 通过 uuid 获取原 dev 节点的 summary status confidence
                dev_info = await self.fact_store.get_dev_fact_by_uuid(
                    dev_uuid=dev_uuid,
                    field_names=["summary", "confidence", "status"]
                )
                if dev_info:
                    old_dev_summary = dev_info["summary"]
                    status = dev_info["status"]
                    confidence = dev_info["confidence"] + 1

                    # print("dev_topic and old_dev_summary")
                    # print(dev_topic)
                    # print(old_dev_summary)

                    # 复用有两种情况：
                    # 1. 该节点本就稳定：只需更新 confidence：+1 并与对应 chunk 节点连接
                    # 2. 该节点暂时不稳定
                    #    confidence、last_update_time、ddl、topic、?status
                    if status == 1:
                        await self.fact_store.update_derived_fact(
                            chunk_uuid=chunk_uuid,
                            dev_uuid=dev_uuid,
                            confidence=confidence,
                        )
                    else:
                        # 扔大模型融合新旧 topic
                        dev_topic = await self.llm_extractor.merge_dev_summary(
                            old_dev_summary,
                            dev_topic,
                        )

                    # 更新 dev 节点， milvus 字段 向量化 dev_topic 并存入milvus
                    return await self.build_dev_fact.merge_chunk_to_dev_fact(
                        dev_uuid=dev_uuid,
                        chunk_uuid=chunk_uuid,
                        topic=dev_topic,
                        confidence=confidence,
                    )
            else: # 创建新的 dev 节点  向量化 topic 并存入milvus
                await self.build_dev_fact.create_dev_fact_milvus(
                    chunk_uuid=chunk_uuid,
                    role_id=role_id,
                    topic=dev_topic,
                )
        return None


    async def build_entity_main(
            self,
            role_id:str,
            chunk_uuid:str,
            chunk_summary: list[float],
    ) -> list:
        # llm 提取实体
        entity_list = await self.llm_extractor.extract_entities_from_summaries(chunk_summary)

        # 创建/连接 实体节点
        if entity_list:
            return await self.build_entity.entity_embed_save(
                role_id=role_id,
                chunk_uuid=chunk_uuid,
                llm_result=entity_list,
            )
        return []


    # 用户画像更新 从 ori_summary dev_summary 联合更新
    async def profile_update_main(
            self,
            role_id: str,
            ori_summary,
            dev_summary,
            target_object: str = "",
    ):
        # 获取旧用户画像节点  user_info_node
        old_profile = await self.user_info_store.get_user_profile(role_id=role_id)
        # llm 融合新新旧画像
        new_profile = await self.llm_extractor.extract_profile_update(
            old_profile=old_profile,
            summary=ori_summary+dev_summary,
            target_object=target_object,
        )

        if new_profile.should_update:
            # user_info_node 更新新画像
            await self.user_info_store.update_user_info_(
                role_id=role_id,
                info_dict=new_profile.updates,
            )



if __name__ == "__main__":
    app = FPMain()

    role_id = "conv-25"
    chunk_uuid = "222d8faf-2476-45a7-aa62-ae2947bfed78"

    import asyncio

    async def h1():
        import app.common.indexing.db_initializer as db_init

        await db_init.init_all_schema()
        result = await app.build_ori_fact.get_chunk_summary_embedding(chunk_uuid)
        print(result)

    asyncio.run(h1())
