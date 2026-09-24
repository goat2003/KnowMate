# from numba.core.types import Optional
from pymilvus import (
    Collection,
    # db, utility
)
import logging
import asyncio
import app.common.config.parameters_config as config
from app.common.client.milvus_client import MilvusClient
from app.DBserver.milvus_repository.vector_service import (
    MetricTypeResolver,
    # MilvusInitializer
)
# from app.common.config.database_conf import milvus_config
# from app.DBserver.milvus_repository.milvus_schemas import COLLECTION_REGISTRY
# from typing import Any, Dict, List, Set, Tuple, Optional
logger = logging.getLogger(__name__)

# # 统一注册不同 collection 的 metric_type
# class MetricTypeResolver:
#     """
#     collection_name -> metric_type 的注册中心
#     """
#
#     # ====== 静态注册表（你当前业务规则就在这里）======
#     _registry = {
#         "chunk_schema": "L2",
#         "ori_fact_schema": "L2",
#         "dev_fact_schema": "L2",
#         "SemanticEntity": "COSINE",
#     }
#
#     # ====== 默认值（兜底）======
#     _default_metric = "L2"
#
#     @classmethod
#     def register(cls, collection_name: str, metric_type: str):
#         """
#         动态新增 / 覆盖规则
#         """
#         cls._registry[collection_name] = metric_type
#
#     @classmethod
#     def unregister(cls, collection_name: str):
#         """
#         删除规则
#         """
#         cls._registry.pop(collection_name, None)
#
#     @classmethod
#     def resolve(cls, collection_name: str) -> str:
#         """
#         核心入口：获取 metric_type
#         """
#         return cls._registry.get(collection_name, cls._default_metric)

class MilvusCRUD:
    """
    Milvus 的轻量 CRUD 封装。

    这个类的职责很明确：
    1. 保证目标 collection 存在，不存在时按注册表自动创建。
    2. 对外提供插入、标量查询、向量检索、删除、更新几个基础接口。
    3. 把上层业务与 pymilvus 的底层调用方式隔离开，避免业务层重复写样板代码。

    当前设计里，MilvusCRUD 不负责业务主键规则，也不负责并发控制。
    这些事情由更上层的 service / lock manager 决定。
    """
    #
    # @staticmethod
    # def _use_database() -> None:
    #     db.using_database(milvus_config.db_name)
    #
    # @staticmethod
    # def ensure_collection(collection_name: str):
    #     """
    #     确保 collection 已连接且存在。
    #
    #     执行流程：
    #     1. 先建立 Milvus 连接。
    #     2. 如果 collection 已存在，直接返回。
    #     3. 如果不存在，则去 `_COLLECTION_REGISTRY` 中查对应 schema 定义。
    #     4. 创建 collection 后，为该 collection 的所有向量字段建立索引。
    #
    #     这里把“可创建哪些 collection”的权限收口在注册表里，
    #     可以避免业务层随便传一个名字就创建出结构不受控的新表。
    #     """
    #     # 先确保 Milvus 已连接
    #     MilvusClient.connect()
    #     MilvusCRUD._use_database()
    #
    #     # 如果 collection 已存在，直接返回
    #     if utility.has_collection(collection_name):
    #         return
    #
    #     # 检查是否允许创建这个 collection
    #     entry = _COLLECTION_REGISTRY.get(collection_name)
    #     if entry is None:
    #         logger.warning(f"Collection {collection_name} not found")
    #         return
    #         # raise ValueError(f"Unknown collection: {collection_name}")
    #
    #     # 根据注册表获取 schema 和向量字段
    #     schema_factory, vector_fields = entry
    #     # 创建 collection
    #     collection = Collection(collection_name, schema=schema_factory())
    #
    #     # 为向量字段创建索引
    #     # HNSW = Hierarchical Navigable Small World
    #     # 它的核心思想是：用“多层图结构”来加速最近邻搜索
    #     # brute force	O(N)	精确但慢
    #     # HNSW	O(log N)	快 + 近似
    #     #
    #     # params：HNSW 结构参数
    #     #
    #     # "M": 8
    #     # 含义：每个向量节点最多连 8 条边。
    #     # | M值         | 效果             |
    #     # | ---------- | -------------- |
    #     # | 小（如 4-8）   | 图更稀疏，省内存，稍慢查询  |
    #     # | 大（如 16-48） | 图更密，精度更高，但更耗内存 |
    #     #
    #     # efConstruction：建图时的搜索宽度
    #     # | efConstruction | 效果         |
    #     # | -------------- | ---------- |
    #     # | 小              | 建索引快，但质量差  |
    #     # | 大              | 建索引慢，但图更优质 |
    #
    #     metric_type = MetricTypeResolver.resolve(collection_name)
    #     index_params = {
    #         "metric_type": metric_type,
    #         "index_type": "IVF_FLAT",
    #         "params": {"nlist": 128}
    #     }
    #
    #     for field_name in vector_fields:
    #         collection.create_index(field_name=field_name, index_params=index_params)
    #
    #     logger.info(f"Created Milvus collection: {collection_name}")
    #
    @staticmethod
    def _build_entities(collection, data: dict):
        """
        把单条字典数据转换成 pymilvus `insert()` 所需的列式结构。

        例如：
        data = {"role_id": "u_1", "chunk_uuid": "c_1", ...}

        会被整理成：
        [
            ["u_1"],
            ["c_1"],
            ...
        ]

        注意这里是“按 schema 字段顺序”构造，而不是按 data 的字典顺序构造。
        这样可以避免字段顺序错乱导致的插入异常。
        """
        entities = []

        for field in collection.schema.fields:
            # 跳过 auto_id
            # 这类字段由 Milvus 自动生成，插入时不需要业务侧传值。
            if field.auto_id:
                continue

            name = field.name

            if name not in data:
                raise ValueError(f"Missing field: {name}")

            value = data[name]

            # 向量字段至少先校验一下类型，避免把字符串、None 等错误值写进去。
            # 更严格的维度校验放在 insert() 里统一做。
            if field.dtype.name == "FLOAT_VECTOR":
                if not isinstance(value, list):
                    raise ValueError("Embedding must be list")

            # pymilvus 的 insert 需要“按列组织”的二维结构。
            # 这里虽然只插入一条数据，也必须把每个字段值再包一层列表。
            entities.append([value])

        return entities

    @staticmethod
    def insert_(collection_name: str, data: dict):
        """
        插入一条记录。

        这里做了两层保护：
        1. 先确保 collection 已存在。
        2. 自动遍历 schema 中的所有向量字段，校验是否存在、维度是否匹配。

        这样上层只需要关心“把完整数据传进来”，
        不需要自己记住每个 collection 的向量字段名和维度。
        """
        collection = Collection(collection_name)

        # 自动检查所有向量字段，防止 embedding 维度不一致。
        # 这类错误如果不在这里尽早拦住，通常会在 Milvus 底层报更难读的异常。
        for field in collection.schema.fields:
            if field.dtype.name == "FLOAT_VECTOR":
                name = field.name
                dim = field.params["dim"]

                if name not in data:
                    raise ValueError(f"Missing vector field: {name}")

                if len(data[name]) != dim:
                    raise ValueError(
                        f"{name} dim must be {dim}"
                    )

        entities = MilvusCRUD._build_entities(
            collection,
            data
        )

        collection.insert(entities)
        collection.flush()

        logger.info(f"Inserted into {collection_name}")

    async def insert(
            self,
            collection_name: str,
            data: dict
    ):
        """
        Async 插入接口。

        将同步 Milvus insert 丢入线程池，
        避免阻塞 asyncio event loop。
        """

        loop = asyncio.get_running_loop()

        result = await loop.run_in_executor(
            None,
            lambda: self.insert_(
                collection_name=collection_name,
                data=data
            )
        )

        return result

    @staticmethod
    def query_(collection_name: str, expr: str, output_fields=None):
        """
        普通标量查询，不做向量相似度搜索。

        典型用途：
        - 按 role_id / chunk_uuid / fact_uuid 等字段精确过滤
        - 做更新前的旧数据读取
        - 做业务回填时的定位查询

        参数：
        - expr: Milvus 的过滤表达式，例如 `role_id == "u_001"`
        - output_fields: 需要返回的字段列表；不传时默认返回全部字段
        """
        # MilvusClient.connect()
        collection = Collection(collection_name)
        # print("collection.index().params: ", collection.index().params)
        # query/search 前通常需要先 load 到内存，避免 collection 尚未加载导致报错。
        collection.load()

        results = collection.query(
            expr=expr,
            output_fields=output_fields or ["*"]
        )

        return results

    async def query(
            self,
            collection_name: str,
            expr: str,
            output_fields=None  # list
    ):
        """
        Async 查询接口。

        将同步 Milvus query 放入线程池，
        防止阻塞 asyncio event loop。
        """

        loop = asyncio.get_running_loop()

        results = await loop.run_in_executor(
            None,
            lambda: self.query_(
                collection_name=collection_name,
                expr=expr,
                output_fields=output_fields
            )
        )

        return results

    # metric_type
    # L2	距离远不远
    # L1	每一维差多少
    # Cosine	方向像不像
    @staticmethod
    def search_(
            collection_name: str,
            embedding: list,
            vector_field: str,
            top_k: int,
            expr=None
    ):
        """
        向量相似度搜索。

        常见用法：
        - 在 `chunk_schema` 上搜 `dia_embedding`，召回对话片段
        - 在 `chunk_schema` 上搜 `summary_embedding`，召回摘要片段
        - 在 `ori_fact_schema` / `dev_fact_schema` 上搜事实摘要向量

        参数说明：
        - embedding: 查询向量，必须和目标向量字段维度一致
        - vector_field: 要检索的向量字段名
        - top_k: 返回前多少条最相近结果
        - expr: 可选过滤表达式，用来先按 role_id 等字段缩小候选范围
        """
        MilvusClient.connect()
        # print("1")
        collection = Collection(collection_name)
        collection.load()

        # # ✅ DEBUG 1：确认总数据量
        # print("num_entities:", collection.num_entities)
        #
        # # ✅ DEBUG 2：确认 expr 过滤结果
        # expr_result = collection.query(
        #     expr=expr,
        #     output_fields=["uuid", "role_id"]
        # )
        #
        # print("expr filtered count:", len(expr_result))

        policy = MetricTypeResolver.resolve(collection_name)
        metric_type = policy["metric"]

        # print(3)
        search_params = {
            "metric_type": metric_type,
            "params": {
                "nprobe": 128
            }
        }

        # print("search_: 开始调用")
        # Milvus search 的 data 参数需要是“查询向量列表”。
        # 即使这里只有一个查询向量，也要写成 [embedding]。
        results = collection.search(
            data=[embedding],
            anns_field=vector_field,
            param=search_params,
            limit=top_k,
            expr=expr,
            output_fields=["*"]
        )

        return results

    # save search
    # 把一个可能耗时、阻塞的操作丢到线程池里执行，避免卡住当前的 asyncio 事件循环。
    # L2	距离远不远
    # L1	每一维差多少
    # Cosine	方向像不像
    async def search(
            self,
            collection_name: str,
            embedding: list,
            top_k: int,
            expr: str,
            vector_field: str,
    ) -> list[dict] | None:
        loop = asyncio.get_running_loop()
        # 在当前用户范围内找最相近的旧 OriginalFact。
        hits = await loop.run_in_executor(
            None,
            lambda: self.search_(
                collection_name=collection_name,
                embedding=list(embedding),
                vector_field=vector_field,
                top_k=top_k,
                expr=expr,
            ),
        )

        if not hits or not hits[0]:
            return None

        result = []

        for top_hit in hits[0]:
            entity = top_hit.entity.to_dict().get("entity", {})

            result.append({
                "distance": top_hit.distance,
                "uuid": entity.get("uuid"),
                "payload": entity
            })

        return result


    async def search_top(
            self,
            collection_name: str,
            embedding: list,
            top_k: int,
            expr: str,
            vector_field: str,
    ) -> dict | None:

        search_list = await self.search(
            collection_name=collection_name,
            embedding=embedding,
            top_k=top_k,
            expr=expr,
            vector_field=vector_field,
        )

        if not search_list:
            return None

        policy = MetricTypeResolver.resolve(collection_name)
        threshold = policy["threshold"]

        top_hit = search_list[0]

        # ✔ 统一判断（不再区分 metric）
        if top_hit["distance"] <= threshold:
            return top_hit

        return None


    @staticmethod
    def delete(collection_name: str, expr: str):
        """
        按过滤表达式删除数据。

        这里是物理删除 collection 中满足条件的行。
        调用方需要确保 expr 足够准确，避免误删。
        """
        collection = Collection(collection_name)
        collection.load()

        res = collection.delete(expr)

        logger.info(f"Deleted from {collection_name}, expr={expr}")

        return res

    @staticmethod
    def update(collection_name: str, data: dict, expr: str):
        """
        更新数据，本质上是“按条件删除旧记录，再插入新记录”。

        之所以这么做，是因为当前这层封装没有引入更复杂的主键 upsert 语义，
        而是统一采用 delete + insert 的方式。

        参数：
        - collection_name: 目标 collection
        - data: 新记录的完整字段内容
        - expr: 用来删除旧记录的过滤条件

        注意：
        1. `data` 应该是“完整的一条新记录”，而不是局部字段 patch。
        2. `expr` 由上层业务决定，例如：
           - chunk_schema: role_id + chunk_uuid + chunk_content_index
           - ori_fact_schema: ori_fact_uuid
           - dev_fact_schema: dev_uuid
        """
        collection = Collection(collection_name)
        collection.load()

        # 先删旧数据，再插入新数据。
        # 如果上层需要并发安全，应在更外层加锁，而不是依赖这里。
        collection.delete(expr)

        # 插入新数据
        entities = MilvusCRUD._build_entities(collection, data)
        collection.insert(entities)
        collection.flush()

        logger.info(f"Updated {collection_name}: expr={expr}")

    @staticmethod
    def update_(
            collection_name: str,
            expr: str,
            updates: dict,
    ):
        """
        更新记录。

        实现方式：
            query -> merge -> delete -> insert

        参数：
            collection_name: collection 名称
            expr: 定位记录的条件
            updates: 需要更新的字段
        """
        collection = Collection(collection_name)
        collection.load()

        # 查询旧记录
        records = collection.query(
            expr=expr,
            output_fields=["*"],
        )

        if not records:
            logger.error(
                f"No record found: collection={collection_name}, expr={expr}"
            )
            return

        if len(records) > 1:
            logger.error(
                f"Multiple records found: collection={collection_name}, expr={expr}"
            )
            return

        # 取完整记录
        data = dict(records[0])

        # 覆盖需要更新的字段
        data.update(updates)

        # 删除旧记录
        collection.delete(expr)

        # 插入新记录
        entities = MilvusCRUD._build_entities(
            collection,
            data,
        )

        collection.insert(entities)
        collection.flush()

        logger.info(
            f"Updated {collection_name}: "
            f"expr={expr}, updates={list(updates.keys())}"
        )


if __name__ == "__main__":
    # 本地手动调试示例。
    # 这一段不是业务正式入口，主要用于快速验证 CRUD 行为是否正常。
    MilvusClient.connect()
    mc = MilvusCRUD()
    memory_data = {
        "role_id": "u_001",
        "chunk_uuid": "r_001",
        "fact_uuid": "",
        "dia_embedding":[0.1]*1536,
        "summary_embedding":[0.2]*1536,
        "chunk_content_index": 0
    }


    user_data1 = {
        "user_id": "u_002",
        "embedding": [0.2] * 1536,
        "age": 20
    }


    doc_data ={
        "doc_id": "d_001",
        "embedding": [0.2] * 1536,
        "title": "Milvus introduction"
    }

    # 示例：插入 chunk_schema 中的一条 chunk 向量记录
    # mc.insert("chunk_schema", memory_data)
    # mc.insert_doc(doc_data)

    query_data = {
        "role_id": "conv-26",
    }

    # 示例：按普通字段过滤查询
    query_result = mc.query_(collection_name="chunk_schema", expr='role_id == "conv-26"')
    print(query_result)
    print(type(query_result))
    print(len(query_result))
    print(list(query_result))

    # 示例：按 dia_embedding 做向量召回
    # search_result = mc.search(
    #     collection_name="chunk_schema",
    #     embedding=[0.1] * 1536
    # )

    """
    对话检索
    res = mc.search(
        "chunk_schema",
        embedding=query_vec,
        vector_field="dia_embedding"
    )
    
    summary 检索
    res = mc.search(
        "chunk_schema",
        embedding=query_vec,
        vector_field="summary_embedding"
    )
    """

    # print(search_result)

    # distance 越小 = 越接近
    # distance 越大 = 越不相似
    # for hit in search_result[0]:
    #     print("id:", hit.id)
    #     print("distance:", hit.distance)  # 相似度/距离
    #     print("entity:", hit.entity)

    chunk_uuid = "240d395d-178d-46c7-a483-ff82d6ae3880"
    MilvusCRUD.update_(
        collection_name="chunk_schema",
        expr=f'chunk_uuid == "{chunk_uuid}"',
        updates={
            "fact_uuid": "20",
        },
    )
    #
    # mc.delete(collection_name="user_collection", expr="age==19")
