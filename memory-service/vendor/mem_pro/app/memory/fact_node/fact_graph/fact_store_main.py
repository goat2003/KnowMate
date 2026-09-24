from app.memory.chunk_node.chunk_graph.chunk_store import ChunkStore
from app.memory.fact_node.fact_graph.fact_store import (
    FactStore,
    GraphORM,
)
# from datetime import datetime, timedelta

class FactStoreMain:
    def __init__(self):
        self.fact_store = FactStore()
        self.graph_orm = GraphORM()

if __name__ == "__main__":
    fs = FactStoreMain()
    # chunk_uuid = "1323"
    # ori_fact_uuid = "1223434"
    ori_fact_uuid = "efd1e29a-cb4a-42c5-977c-a18df4ff1fcf"
    chunk_uuids = ["e59e7e36-f192-47b1-8003-19cb3ebc5272",
                  "2c6ae9d5-132f-4678-a610-c2a0a784ec79",
                  "7a6fc60a-0d7d-4921-91d4-48979d8d7e7e"]

    dev_uuid = "0ca80b1e-2b5e-4cfa-b89f-c30802afa496"
    role_id = "222"
    summary = "ert"  # LLM 生成的 topic 摘要（Milvus 向量化用）
    importance = 0.1
    confidence = 2

    import asyncio

    # result = asyncio.run(fs.fact_store.get_ori_fact_by_uuid(
    #     # dev_uuid=dev_uuid,
    #     ori_fact_uuid = ori_fact_uuid,
    #     field_names = ["confidence", "importance"],
    # ))
    # print(result)
    # print(type(result))
    # print(result["confidence"])
    # print(result["importance"])

    # result = asyncio.run(fs.fact_store.delete_expired_derived_facts_by_status(
    #     datetime.now() + timedelta(days=90)
    # ))

    async def main():
        ori_fact_uuid = "550b6652-0844-4c8c-a10c-462a3b3a3e0b"

        result = await fs.graph_orm.find(
            "OriginalFact",
            ori_fact_uuid
        ).in_("ChunkNode").run()

        print(result)


    # entity 边搜索获取对面节点
    async def main1():
        entity_uuid = "4f2a4347-b2a2-4469-9c88-6fa46ee762b2"

        result = await fs.graph_orm.find(
            "Entity",
            entity_uuid
        ).both(
            "Entity"
        ).rel(
            "RELATES_TO"
        ).run()

        print(result)

    # 测试用 仅ori-chunk 边连接
    async def main2():
        for chunk_uuid in chunk_uuids:
            await fs.fact_store.link_chunk_to_fact(chunk_uuid, ori_fact_uuid)

    # asyncio.run(main2())

    result = asyncio.run(fs.fact_store.get_original_fact_summary(ori_fact_uuid))
    print(result)