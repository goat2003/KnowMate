"""
数据库初始化编排

统一入口，按正确顺序调用 Neo4j Schema + Milvus Collection 初始化。
供 memory_service 和脚本调用。
"""

import logging

from app.common.indexing.milvus_schema import init_milvus_collections
from app.common.indexing.neo4j_schema import init_all_neo4j_schema
from app.DBserver.milvus_repository.vector_service import MilvusInitializer

logger = logging.getLogger(__name__)


async def init_all_schema() -> None:
    """一站式初始化所有数据库 Schema（Neo4j 索引/约束 + Milvus Collection）"""
    await init_all_neo4j_schema()
    milvus_init = MilvusInitializer()
    milvus_init.init_collections()
    logger.info("[Initializer] 全部数据库 Schema 初始化完成")


if __name__ == "__main__":
    import asyncio
    asyncio.run(init_all_schema())
