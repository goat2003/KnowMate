from app.memory.fact_node.fact_service.llm_extractor import FactLLMExtractor
from app.memory.chunk_node.chunk_graph.chunk_store import ChunkStore
from app.memory.user_info_node.user_info_graph.user_info_store import UserInfoStore
from app.memory.fact_node.fact_service.fact_pipeline_main import FPMain
from app.memory.fact_node.fact_graph.fact_store import FactStore


class FactMain:
    def __init__(self):
        self.user_info_store = UserInfoStore()
        self.extractor = FactLLMExtractor()
        self.chunk_store = ChunkStore()
        self.fact_pipeline_main = FPMain()
        self.fact_store = FactStore()

    async def main(
            self,
            role_id,
            chunk_uuid: str,
            target_object: str = "",
    ):
        # ======== Step 1 获取 chunk 的 summary 和 embedding =========
        chunk_summary, chunk_embedding = await self.fact_pipeline_main.build_ori_fact.get_chunk_summary_embedding(chunk_uuid)
        print(chunk_summary, chunk_embedding)

        # ======== Step 1.5 判断该chunk节点是否已分析过事实节点和实体节点 =========
        result = await self.fact_store.get_chunk_relation_status(chunk_uuid)
        ori_summary = ""
        dev_summary = ""

        if result and not result["has_fact"]:
            # ======== Step 2 创建 OriginalFact 节点 =========
            print("Step 2 创建 OriginalFact 节点")
            ori_summary = await self.fact_pipeline_main.build_ori_fact_main(
                role_id=role_id,
                chunk_uuid=chunk_uuid,
                chunk_summary=chunk_summary,
                chunk_embedding=chunk_embedding,
                target_object=target_object,
            )

        if result and not result["derived_from"]:
            # ======== Step 3 创建 DerivedFact 节点 =========
            print("Step 3 创建 DerivedFact 节点")
            dev_summary = await self.fact_pipeline_main.build_dev_fact_main(
                role_id=role_id,
                chunk_uuid=chunk_uuid,
                chunk_summary=chunk_summary,
                target_object=target_object,
            )

        if result and not result["has_entity"]:
            # ======== Step 4 创建 Entity 节点 =========
            print("Step 4 创建 Entity 节点")
            entity_uuids = await self.fact_pipeline_main.build_entity_main(
                role_id=role_id,
                chunk_uuid=chunk_uuid,
                chunk_summary=chunk_summary,
            )
            # 执行 entity 边连接
            await self.fact_store.create_entity_relates_edges(
                entity_uuids=entity_uuids)

        # 用户画像更新
        ori_summary = ori_summary or ""
        dev_summary = dev_summary or ""

        if ori_summary or dev_summary:
            await self.fact_pipeline_main.profile_update_main(
                role_id=role_id,
                ori_summary=ori_summary,
                dev_summary=dev_summary,
                target_object=target_object,
            )

if __name__ == "__main__":
    extractor = FactMain()
    role_id = "conv-25"
    chunk_uuid = "222d8faf-2476-45a7-aa62-ae2947bfed78"

    import asyncio

    asyncio.run(extractor.main(role_id, chunk_uuid))
