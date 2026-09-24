"""
Milvus Collection 初始化

MilvusManager.__init__() 自动创建所有 Collection（EpisodeCluster, EpisodeClass,
SemanticEntity, SemanticFactEdge），本模块提供显式的初始化验证接口。
"""

import logging

logger = logging.getLogger(__name__)

ALL_COLLECTIONS = [
    "chunk_schema",
    "ori_fact_schema",
    "dev_fact_schema",
    "SemanticEntity",
]


def init_milvus_collections() -> None:
    """初始化并验证所有 Milvus Collection"""
    try:
        from app.common.manager.milvus_manager import MilvusManager

        MilvusManager()

        from pymilvus import utility

        for col_name in ALL_COLLECTIONS:
            if utility.has_collection(col_name):
                logger.info(f"[Schema] Milvus Collection 已就绪: {col_name}")
            else:
                logger.warning(f"[Schema] Milvus Collection 未创建: {col_name}")

        logger.info("[Schema] Milvus Collection 初始化完成")
    except Exception as e:
        logger.warning(f"[Schema] Milvus 初始化失败: {e}")
