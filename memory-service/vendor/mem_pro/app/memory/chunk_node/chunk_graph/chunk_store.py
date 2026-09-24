"""
chunk 存储原始对话

role_id
chunk_uuid
content: dict
rewrite: str
"""

from datetime import datetime
from typing import List, Dict, Optional

from app.common.manager.neo4j_manager import Neo4jManager
from app.memory.tools_service import ToolService
from uuid import uuid4

class ChunkStore:
    def __init__(self):
        self.manager = Neo4jManager.get_instance()
        self.tool_service = ToolService()

    # async def uniq_chunk(self):
    #     query = """
    #         CREATE CONSTRAINT chunk_unique IF NOT EXISTS
    #         FOR (ch:ChunkNode)
    #         REQUIRE (ch.hash_val) IS UNIQUE
    #         """
    #     await self.manager.execute_write(query, {})

    async def create_chunk(
            self,
            role_id: str,
            dialogue: str,
            summary: str,
            timestamp: int,
            hash_val: str
    ) -> str:
        """
        创建 chunk 节点
        每一个 chunk 节点只与 user_info 和 fact 节点相连

        Args:
            chunk_uuid: 会话节点的 uuid
            role_id: 用户ID
            contents: 对话内容列表
            summary: 对话内容列表的改写摘要
            valid_time: 消息时间（ISO 格式字符串）
            create_time: 节点创建时间
            hash_val: 对完整节选对话进行哈希，避免重复分析相同对话

        Returns:
            str: chunk节点的 UUID
        """

        query = """
            CREATE (ch:ChunkNode)
            SET
                ch.role_id = $role_id,
                ch.chunk_uuid = $chunk_uuid,
                ch.create_time = $create_time,
                ch.valid_time = $valid_time,
                ch.summary = $summary,
                ch.contents = $contents,
                ch.hash_val = $hash_val

            WITH ch
            MATCH (ui:UserInfoNode {role_id: $role_id})

            MERGE (ui)-[:HAS_CHUNK]->(ch)

            RETURN ch.chunk_uuid AS chunk_uuid
            """

        # timestamp_ilt =[datetime.fromtimestamp(ts) for ts in timestamp]

        params = {
            "chunk_uuid": str(uuid4()),
            "role_id": role_id,
            "contents": dialogue,
            "summary": summary,
            "create_time": datetime.now(),
            "valid_time": datetime.fromtimestamp(timestamp),
            "hash_val": hash_val
        }

        result = await self.manager.execute_write(query, params)

        return result[0]["chunk_uuid"] if result else None

    # 通过 uuid 获取该 chunk 节点
    async def get_chunk_by_uuid(
            self,
            chunk_uuid: str
    ) -> List[Dict]:
        """
        获取指定 uuid 的 chunk 节点

        Args:
            chunk_uuid: chunk 节点 ID

        Returns:
            List[Dict]: chunk 节点信息列表
        """

        query = """
            MATCH (ch:ChunkNode {chunk_uuid: $chunk_uuid})
            RETURN ch
        """

        params = {
            "chunk_uuid": chunk_uuid
        }

        result = await self.manager.execute_write(query, params)

        return result if result else []


    # 获取该 role_id 下的所有 chunk
    async def get_chunk_by_role_id(
            self,
            role_id: str
    ) -> List[Dict]:
        """
        获取指定 role_id 下的所有 chunk 节点

        Args:
            role_id: 用户ID

        Returns:
            List[Dict]: chunk 节点信息列表
        """

        query = """
            MATCH (ch:ChunkNode {role_id: $role_id})
            RETURN ch
        """

        params = {
            "role_id": role_id
        }

        result = await self.manager.execute_write(query, params)

        return result if result else []

    async def get_chunk_summary_by_role_id(
            self,
            role_id: str
    ) -> List[str]:
        query = """
            MATCH (ch:ChunkNode {role_id: $role_id})
            RETURN ch.summary AS summary
        """

        params = {
            "role_id": role_id
        }

        result = await self.manager.execute_write(query, params)

        if not result:
            return []

        return [
            summary
            for item in result
            if item.get("summary")
            for summary in item["summary"]
        ]

    async def get_chunk_summary_by_uuid(
            self,
            chunk_uuid: str
    ) -> Optional[str]:
        query = """
            MATCH (ch:ChunkNode {chunk_uuid: $chunk_uuid})
            RETURN ch.summary AS summary
        """

        params = {
            "chunk_uuid": chunk_uuid
        }

        result = await self.manager.execute_write(query, params)

        if not result:
            return None

        return result[0]["summary"] if result else None


    # 判断当前节选对话是否被分析过
    # 若有该hash值存在，则不对当前对话进行大模型分析
    async def query_exist_by_hash(
            self,
            hash_val: str,
            role_id: str
    ) -> list[str] | None:
        """
        根据 hash_val 判断 chunk 是否已存在

        Args:
            hash_val: 对话内容的哈希值
            role_id: 用户id

        Returns:
            bool: 是否存在
        """

        query = """
            MATCH (ch:ChunkNode)
            WHERE ch.hash_val = $hash_val
              AND ch.role_id = $role_id
            RETURN collect(ch.chunk_uuid) AS chunk_uuids
        """

        params = {"hash_val": hash_val, "role_id": role_id, }

        result = await self.manager.execute_query(query, params)

        if not result:
            return None

        chunk_uuids = result[0]["chunk_uuids"]
        return chunk_uuids if chunk_uuids else None

