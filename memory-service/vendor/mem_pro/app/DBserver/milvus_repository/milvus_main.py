from app.DBserver.milvus_repository.milvus_operate import MilvusCRUD
from app.common.client.milvus_client import MilvusClient


class BDMain:
    def __init__(self):
        self.milvusCRUD = MilvusCRUD()


if __name__ == "__main__":
    MilvusClient.connect()
    bm = BDMain()

    import asyncio
    role_id = "conv-91"
    name = "Beijing"
    entity_type = "Location"
    import numpy as np

    embedding = np.random.random(1536).tolist()
    search_result = bm.milvusCRUD.search_(
        collection_name="ori_fact_schema",
        embedding=embedding,
        top_k=4,
        expr=(
            f'role_id == "{role_id}"'
            # f'role_id == "{role_id}" '
            # f'AND name == "{name}" '
            # f'AND type == "{entity_type}"'
        ),
        # vector_field="semantic_embedding",
        vector_field="summary_embedding",
    )
    print(search_result)
    print(type(search_result))
    # print(len(search_result[0]))

    search_result1 = asyncio.run(bm.milvusCRUD.query(
        collection_name="ori_fact_schema",
        expr=(
            f'role_id == "{role_id}"'
        ),
        output_fields=["summary"]
    ))

    print(search_result1)

    # for item in search_result1:
    #     embed = item["summary_embedding"]
    #     import numpy as np
    #
    #     cos = np.dot(embedding, embed) / (
    #             np.linalg.norm(embedding) * np.linalg.norm(embed)
    #     )
    #
    #     print(cos)
    # print(len(search_result1))



    #
    #
    #
    # search_result3 = asyncio.run(bm.milvusCRUD.search(
    #     collection_name="ori_fact_schema",
    #     embedding=embedding,
    #     top_k=4,
    #     expr=(
    #         f'role_id == "{role_id}"'
    #         # f'role_id == "{role_id}" '
    #         # f'AND name == "{name}" '
    #         # f'AND type == "{entity_type}"'
    #     ),
    #     # vector_field="semantic_embedding",
    #     vector_field="summary_embedding",
    # ))
    #
    # print(len(search_result3))
    # print(search_result3)
