"""
数据库清理

提供 Neo4j / Milvus / MongoDB 的数据清理函数，供 memory_service 和脚本调用。
"""

import logging

from app.common.manager.neo4j_manager import Neo4jManager

logger = logging.getLogger(__name__)


async def clear_neo4j_data(manager: Neo4jManager, batch_size: int = 10000) -> dict:
    """批量删除 Neo4j 中所有节点和关系

    Returns:
        {"deleted_nodes": int, "deleted_rels": int}
    """
    deleted_rels = 0
    while True:
        result = await manager.execute_write(
            f"MATCH ()-[r]->() "
            f"WITH r LIMIT {batch_size} "
            f"DELETE r "
            f"RETURN count(r) AS deleted",
            {},
        )
        batch_deleted = result[0]["deleted"] if result else 0
        deleted_rels += batch_deleted
        if batch_deleted == 0:
            break
    logger.info(f"[Cleaner] 关系已删除: {deleted_rels:,}")

    deleted_nodes = 0
    while True:
        result = await manager.execute_write(
            f"MATCH (n) "
            f"WITH n LIMIT {batch_size} "
            f"DELETE n "
            f"RETURN count(n) AS deleted",
            {},
        )
        batch_deleted = result[0]["deleted"] if result else 0
        deleted_nodes += batch_deleted
        if batch_deleted == 0:
            break
    logger.info(f"[Cleaner] 节点已删除: {deleted_nodes:,}")

    return {"deleted_nodes": deleted_nodes, "deleted_rels": deleted_rels}


async def clear_neo4j_indexes_and_constraints(manager: Neo4jManager) -> None:
    """删除所有用户创建的 Neo4j 索引和约束（保留系统 LOOKUP 索引）"""
    # 约束
    try:
        constraints = await manager.execute_query(
            "SHOW CONSTRAINTS YIELD name RETURN name", {}
        )
        for c in constraints:
            name = c["name"]
            try:
                await manager.execute_write(f"DROP CONSTRAINT `{name}`", {})
                logger.info(f"[Cleaner] 约束已删除: {name}")
            except Exception as e:
                logger.warning(f"[Cleaner] 删除约束 {name} 失败: {e}")
        if not constraints:
            logger.info("[Cleaner] 无约束需要清理")
    except Exception as e:
        logger.warning(f"[Cleaner] 获取约束列表失败: {e}")

    # 索引（排除系统内置的 LOOKUP 索引）
    try:
        indexes = await manager.execute_query(
            "SHOW INDEXES YIELD name, type "
            "WHERE type <> 'LOOKUP' "
            "RETURN name",
            {},
        )
        for idx in indexes:
            name = idx["name"]
            try:
                await manager.execute_write(f"DROP INDEX `{name}`", {})
                logger.info(f"[Cleaner] 索引已删除: {name}")
            except Exception as e:
                logger.warning(f"[Cleaner] 删除索引 {name} 失败: {e}")
        if not indexes:
            logger.info("[Cleaner] 无索引需要清理")
    except Exception as e:
        logger.warning(f"[Cleaner] 获取索引列表失败: {e}")


def clear_milvus_collections() -> None:
    """删除所有 Milvus Collection 并重置 MilvusManager 单例"""
    try:
        from pymilvus import Collection, connections, utility

        from app.common.config.database_conf import milvus_config

        connections.connect(
            "clear_script",
            host=milvus_config.host,
            port=milvus_config.port,
            timeout=milvus_config.timeout,
            db_name=milvus_config.db_name,
        )

        all_collections = [
            "SemanticEntity",
            "EpisodeCluster",
            "EpisodeClass",
        ]
        for col_name in all_collections:
            if utility.has_collection(col_name, using="clear_script"):
                col = Collection(col_name, using="clear_script")
                col.drop()
                logger.info(f"[Cleaner] Milvus Collection 已删除: {col_name}")
            else:
                logger.debug(f"[Cleaner] Milvus Collection 不存在: {col_name}")

        connections.disconnect("clear_script")

        try:
            connections.disconnect("default")
        except Exception:
            pass

        from app.common.manager.milvus_manager import MilvusManager

        MilvusManager._initialized = False
        MilvusManager._instance = None

        logger.info("[Cleaner] Milvus 全部 Collection 清理完成")
    except Exception as e:
        logger.warning(f"[Cleaner] Milvus 清理失败: {e}")


def clear_mongodb_data() -> None:
    """清理 MongoDB 用户画像和实体映射数据"""
    try:
        from pymongo import MongoClient

        from app.common.config.database_conf import mongodb_config

        client = MongoClient(mongodb_config.uri)
        db = client[mongodb_config.db_name]

        # 用户画像
        profile_col = db[mongodb_config.collection_name]
        count = profile_col.count_documents({})
        if count > 0:
            result = profile_col.delete_many({})
            logger.info(
                f"[Cleaner] MongoDB 用户画像已清理: "
                f"{mongodb_config.db_name}.{mongodb_config.collection_name} "
                f"删除 {result.deleted_count} 条"
            )

        # 实体映射
        entity_col = db[mongodb_config.entity_collection_name]
        count = entity_col.count_documents({})
        if count > 0:
            result = entity_col.delete_many({})
            logger.info(
                f"[Cleaner] MongoDB 实体映射已清理: "
                f"{mongodb_config.db_name}.{mongodb_config.entity_collection_name} "
                f"删除 {result.deleted_count} 条"
            )

        # 兼容旧库
        legacy_db_name = "test_database"
        if legacy_db_name != mongodb_config.db_name:
            legacy_db = client[legacy_db_name]
            for col_name in ["test_collection", "session_entity_maps"]:
                legacy_col = legacy_db[col_name]
                c = legacy_col.count_documents({})
                if c > 0:
                    r = legacy_col.delete_many({})
                    logger.info(
                        f"[Cleaner] MongoDB 旧库清理: "
                        f"{legacy_db_name}.{col_name} 删除 {r.deleted_count} 条"
                    )

        client.close()
    except Exception as e:
        logger.warning(f"[Cleaner] MongoDB 清理失败: {e}")
