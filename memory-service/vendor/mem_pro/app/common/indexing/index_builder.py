"""
双向索引构建服务

功能:
1. 正向索引：EpisodicNode.fact_edge_ids 维护
2. 反向索引：EntityEdge.episodes 维护（在事实融合时完成）
3. 索引一致性验证
"""

import logging
from typing import List, Dict, Any

from app.common.manager.neo4j_manager import Neo4jManager

logger = logging.getLogger(__name__)


class IndexBuilder:
    """
    双向索引构建器

    职责:
    1. 在创建事实边后，更新源头情节的 fact_edge_ids
    2. 验证索引一致性
    3. 提供反向查询接口

    Example:
        ... builder = IndexBuilder(neo4j_manager)
        ... await builder.update_episode_index(
        ...     episode_uuid="ep_001",
        ...     fact_edge_uuids=["edge_001", "edge_002"]
        ... )
    """

    def __init__(self, manager: Neo4jManager):
        """
        初始化索引构建器

        Args:
            manager: Neo4j 连接管理器
        """
        self.manager = manager

    async def update_episode_index(
        self,
        episode_uuid: str,
        fact_edge_uuids: List[str]
    ) -> bool:
        """
        更新情节节点的正向索引

        将新创建/更新的事实边 UUID 追加到情节节点的 fact_edge_ids 属性。

        Args:
            episode_uuid: 情节节点UUID
            fact_edge_uuids: 事实边UUID列表

        Returns:
            bool: 是否更新成功
        """
        if not fact_edge_uuids:
            logger.debug(f"No fact edges to add for episode_node {episode_uuid[:8]}...")
            return True

        query = """
        MATCH (ep:EpisodicNode {uuid: $episode_uuid})
        SET ep.fact_edge_ids = ep.fact_edge_ids + $new_edge_ids
        RETURN ep.fact_edge_ids AS fact_edge_ids
        """

        try:
            result = await self.manager.execute_query(
                query,
                {
                    "episode_uuid": episode_uuid,
                    "new_edge_ids": fact_edge_uuids
                }
            )

            if result:
                updated_ids = result[0]["fact_edge_ids"]
                logger.info(
                    f"OK Updated episode_node index: {episode_uuid[:8]}... "
                    f"({len(fact_edge_uuids)} new edges, total: {len(updated_ids)})"
                )
                return True

            logger.error(f"FAIL Episode not found: {episode_uuid}")
            return False

        except Exception as e:
            logger.error(f"FAIL Failed to update episode_node index: {e}")
            return False

    async def get_episode_facts(
        self,
        episode_uuid: str
    ) -> List[Dict[str, Any]]:
        """
        获取情节贡献的所有事实（正向查询）

        使用 fact_edge_ids 直接查询，避免图遍历。

        Args:
            episode_uuid: 情节节点UUID

        Returns:
            List[Dict[str, Any]]: 事实边列表
        """
        # 步骤1: 获取 fact_edge_ids
        query_get_ids = """
        MATCH (ep:EpisodicNode {uuid: $episode_uuid})
        RETURN ep.fact_edge_ids AS fact_edge_ids
        """

        result = await self.manager.execute_query(
            query_get_ids,
            {"episode_uuid": episode_uuid}
        )

        if not result or not result[0].get("fact_edge_ids"):
            return []

        edge_ids = result[0]["fact_edge_ids"]

        # 步骤2: 批量查询事实边
        query_get_edges = """
        MATCH (s)-[r:RELATES_TO]->(t)
        WHERE r.uuid IN $edge_ids
        RETURN s.name AS source, r.name AS relation, r.fact AS fact,
               t.name AS target, r.uuid AS uuid
        """

        edges = await self.manager.execute_query(
            query_get_edges,
            {"edge_ids": edge_ids}
        )

        return edges if edges else []

    async def get_fact_episodes(
        self,
        fact_edge_uuid: str
    ) -> List[Dict[str, Any]]:
        """
        获取事实的所有来源情节（反向查询）

        使用 EntityEdge.episodes 属性直接查询。

        Args:
            fact_edge_uuid: 事实边UUID

        Returns:
            List[Dict[str, Any]]: 情节节点列表
        """
        query = """
        MATCH (s)-[r:RELATES_TO]->(t)
        WHERE r.uuid = $edge_uuid
        UNWIND r.episodes AS episode_uuid
        MATCH (ep:EpisodicNode {uuid: episode_uuid})
        RETURN ep.uuid AS uuid, ep.content AS content, ep.valid_at AS valid_at
        ORDER BY ep.valid_at DESC
        """

        result = await self.manager.execute_query(
            query,
            {"edge_uuid": fact_edge_uuid}
        )

        return result if result else []

    async def verify_index_consistency(
        self,
        episode_uuid: str
    ) -> Dict[str, Any]:
        """
        验证双向索引一致性

        检查:
        1. episode_node.fact_edge_ids 中的边是否都存在
        2. 这些边的 episodes 属性是否都包含该 episode_uuid

        Args:
            episode_uuid: 情节节点UUID

        Returns:
            Dict[str, Any]: 验证结果
                - consistent: 是否一致
                - issues: 问题列表
        """
        issues = []

        # 获取 fact_edge_ids
        query = """
        MATCH (ep:EpisodicNode {uuid: $episode_uuid})
        RETURN ep.fact_edge_ids AS fact_edge_ids
        """

        result = await self.manager.execute_query(
            query,
            {"episode_uuid": episode_uuid}
        )

        if not result:
            return {"consistent": False, "issues": ["Episode not found"]}

        edge_ids = result[0].get("fact_edge_ids", [])

        # 检查每个边
        for edge_id in edge_ids:
            # 检查边是否存在
            query_check = """
            MATCH (s)-[r:RELATES_TO]->(t)
            WHERE r.uuid = $edge_id
            RETURN r, $episode_uuid IN r.episodes AS has_reverse
            """

            check_result = await self.manager.execute_query(
                query_check,
                {"edge_id": edge_id, "episode_uuid": episode_uuid}
            )

            if not check_result:
                issues.append(f"Edge {edge_id} does not exist")
            elif not check_result[0]["has_reverse"]:
                issues.append(f"Edge {edge_id} does not have reverse reference")

        return {
            "consistent": len(issues) == 0,
            "issues": issues
        }

    async def rebuild_episode_index(
        self,
        episode_uuid: str
    ) -> bool:
        """
        重建情节的正向索引

        扫描所有 RELATES_TO 边，找出 episodes 属性包含该 episode_uuid 的边，
        然后更新 episode_node.fact_edge_ids。

        Args:
            episode_uuid: 情节节点UUID

        Returns:
            bool: 是否重建成功
        """
        query = """
        // 查找所有相关的边
        MATCH (s)-[r:RELATES_TO]->(t)
        WHERE $episode_uuid IN r.episodes
        WITH collect(r.uuid) AS edge_ids

        // 更新情节节点
        MATCH (ep:EpisodicNode {uuid: $episode_uuid})
        SET ep.fact_edge_ids = edge_ids
        RETURN length(ep.fact_edge_ids) AS count
        """

        try:
            result = await self.manager.execute_query(
                query,
                {"episode_uuid": episode_uuid}
            )

            if result:
                count = result[0]["count"]
                logger.info(f"OK Rebuilt index for episode_node {episode_uuid[:8]}... ({count} edges)")
                return True

            return False

        except Exception as e:
            logger.error(f"FAIL Failed to rebuild index: {e}")
            return False

