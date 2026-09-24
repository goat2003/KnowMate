"""
Milvus 向量数据库连接管理器

职责：
- 管理 Milvus 连接（单例模式）
- 自动创建数据库和 Collection
- 提供 EpisodeCluster / EpisodeClass 的 upsert 和 search 方法
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    db,
    utility,
)

from app.common.config.database_conf import milvus_config
from app.common.config.embedder_conf import embed_config

logger = logging.getLogger(__name__)

# Collection 名称常量
CLUSTER_COLLECTION = "EpisodeCluster"
CLASS_COLLECTION = "EpisodeClass"
SEMANTIC_ENTITY_COLLECTION = "SemanticEntity"
EMBEDDING_DIM = embed_config.dimensions


def _to_millis(value: Any) -> int:
    """将 datetime / Neo4j DateTime 转换为毫秒时间戳"""
    if value is None:
        return 0
    if hasattr(value, "to_native"):
        value = value.to_native()
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


class MilvusManager:
    """
    Milvus 连接管理器（单例）

    在第一次实例化时自动：
    1. 连接 Milvus
    2. 创建数据库（如果不存在）
    3. 创建 EpisodeCluster / EpisodeClass Collection（如果不存在）
    """

    _instance: Optional["MilvusManager"] = None
    _initialized: bool = False

    def __new__(cls) -> "MilvusManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if MilvusManager._initialized:
            if milvus_config.db_name != "default":
                db.using_database(milvus_config.db_name)
            return
        MilvusManager._initialized = True

        # 连接
        logger.info(f"连接 Milvus: {milvus_config.host}:{milvus_config.port}")
        connections.connect(
            "default",
            host=milvus_config.host,
            port=milvus_config.port,
            timeout=milvus_config.timeout,
        )

        # 创建数据库
        if milvus_config.db_name != "default":
            dbs = db.list_database()
            if milvus_config.db_name not in dbs:
                db.create_database(milvus_config.db_name)
                logger.info(f"已创建 Milvus 数据库: {milvus_config.db_name}")
            db.using_database(milvus_config.db_name)
            logger.info(f"已切换到数据库: {milvus_config.db_name}")

        # 创建 Collection
        # self._ensure_cluster_collection()
        # self._ensure_class_collection()
        # self._ensure_semantic_entity_collection()

        logger.info("MilvusManager 初始化完成")

    # ==================== 连接管理 ====================

    def close(self):
        """断开 Milvus 连接"""
        connections.disconnect("default")
        MilvusManager._initialized = False
        MilvusManager._instance = None
        logger.info("Milvus 连接已断开")
