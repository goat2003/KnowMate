"""
用户基本信息节点作为该用户记忆库的最中心节点 UserInfoNode
所有记忆、实体都需要围绕这个中心节点展开

role_id
info_uuid
basic_info: 名字、年龄、职业、住址、工作地址
            职业、住址、工作地址：动态更新，保留旧信息+时间截点
preference: 偏好  可能未来会来自于派生fact
            动态更新：新偏好加入；矛盾偏好、明确不是偏好的执行覆盖
skill:
create_time:
last_update_time:

职责：封装所有 UserInfoNode 相关的 Cypher 操作
"""
import logging
logger = logging.getLogger(__name__)

from app.common.manager.neo4j_manager import Neo4jManager
from app.memory.tools_service import ToolService
from datetime import datetime
from uuid import uuid4
from typing import Dict

# 需要的字段
REQUIRED_PROFILE_FIELDS = ("basic_info", "preference", "skill")


class UserInfoStore:
    """UserInfoNode 的 CRUD 操作"""

    def __init__(self):
        self.manager = Neo4jManager.get_instance()
        self.tools_service = ToolService()

    async def uniq_user_info(self):
        """
        为 UserInfoNode 建立 role_id 唯一约束
        """
        query = """
            CREATE CONSTRAINT user_info_unique IF NOT EXISTS
            FOR (ui:UserInfoNode)
            REQUIRE ui.role_id IS UNIQUE
            """
        await self.manager.execute_write(query, {})

    """
    info_dict:  每个字段是一句话描述
    {
        basic_info: 
        preference:
        skill:
    }
    """

    async def create_user_info(
            self,
            role_id: str,
            info_dict: dict
    ) -> str:
        info_dict = self._validate_info_dict(info_dict)
        query = """
        MERGE (ui:UserInfoNode {
            role_id: $role_id
        })
        ON CREATE SET
            ui.user_info_uuid = $user_info_uuid,
            ui.create_time = $create_time,
            ui.last_update_time = $last_update_time,
            ui.basic_info = $basic_info,
            ui.preference = $preference,
            ui.skill = $skill
        RETURN ui.user_info_uuid AS user_info_uuid
        """

        params = {
            'user_info_uuid': str(uuid4()),
            'role_id': role_id,
            'create_time': datetime.now(),
            'last_update_time': datetime.now(),
            'basic_info': info_dict['basic_info'],
            'preference': info_dict['preference'],
            'skill': info_dict['skill']
        }

        result = await self.manager.execute_write(query, params)
        return result[0]["user_info_uuid"]

    @staticmethod
    # 画像字段验证、比较、合并等工具函数，确保 UserInfoStore 的核心逻辑清晰且专注于数据库操作。
    def _validate_info_dict(info_dict: dict) -> dict | None:
        missing_fields = [field for field in REQUIRED_PROFILE_FIELDS if field not in info_dict]
        if missing_fields:
            logger.error(f"info_dict missing fields: {', '.join(missing_fields)}")
            return None

        invalid_fields = [
            field for field in REQUIRED_PROFILE_FIELDS
            if not isinstance(info_dict[field], str)
        ]
        if invalid_fields:
            logger.error(f"info_dict fields must be strings: {', '.join(invalid_fields)}")
            return None

        return {field: info_dict[field].strip() for field in REQUIRED_PROFILE_FIELDS}

    async def query_by_role_id(self, role_id: str) -> dict | None:
        """
        根据 role_id 查询 UserInfoNode
        """
        query = """
        MATCH (ui:UserInfoNode {role_id: $role_id})
        RETURN 
            ui.user_info_uuid AS user_info_uuid,
            ui.role_id AS role_id,
            ui.basic_info AS basic_info,
            ui.preference AS preference,
            ui.skill AS skill,
            ui.create_time AS create_time,
            ui.last_update_time AS last_update_time
        LIMIT 1
        """

        params = {
            "role_id": role_id
        }

        result = await self.manager.execute_write(query, params)

        if not result:
            return None

        return result[0]

    # 通过问卷更新 user_info_node 三个用户画像属性
    async def upsert_user_info_(self, role_id: str, info_dict: dict) -> str:
        info_dict = self._validate_info_dict(info_dict)

        query = """
        MERGE (ui:UserInfoNode {role_id: $role_id})

        ON CREATE SET
            ui.user_info_uuid = randomUUID(),
            ui.create_time = datetime()

        SET
            ui.basic_info = $basic_info,
            ui.preference = $preference,
            ui.skill = $skill,
            ui.last_update_time = datetime()

        RETURN ui.user_info_uuid AS user_info_uuid
        """

        params = {
            "role_id": role_id,
            "basic_info": info_dict["basic_info"],
            "preference": info_dict["preference"],
            "skill": info_dict["skill"],
        }

        result = await self.manager.execute_write(query, params)

        return result[0]["user_info_uuid"]

    # 带有重试功能的更新写入操作
    async def upsert_user_info(self, role_id: str, info_dict: dict):
        return await self.tools_service.safe_retry(
            func=self.upsert_user_info_,
            role_id=role_id,
            info_dict=info_dict
        )

    # 直接获取该用户三类画像的描述
    async def get_user_profile(self, role_id: str) -> Dict[str, str]:
        """读取 UserInfoNode 的三个画像字段。

        调用方：阶段1 提取前获取最新画像供 LLM 参考；
               每次 safe_profile_update 后重新读取最新版本。
        coalesce() 将 NULL 转空字符串，避免上层到处写 or "" 判空。
        """
        query = """
        MATCH (u:UserInfoNode {role_id: $role_id})
        RETURN
            coalesce(u.basic_info, '') AS basic_info,
            coalesce(u.preference, '') AS preference,
            coalesce(u.skill, '') AS skill
        LIMIT 1
        """
        # 读操作用 execute_query（非写事务），效率更高
        rows = await self.manager.execute_query(query, {"role_id": role_id})
        if not rows:
            # 上游必须保证 UserInfoNode 存在（问卷阶段已创建）
            raise ValueError(f"User profile not found for role_id={role_id}")

        row = rows[0]  # LIMIT 1 保证最多一行
        return {
            "basic_info": str(row.get("basic_info") or ""),  # coalesce 已兜底，or "" 二次兜底
            "preference": str(row.get("preference") or ""),
            "skill": str(row.get("skill") or ""),
        }

    # 对话提取内容对画像的更新

    # ✔ 允许更新的字段白名单（非常重要）
    _UPDATABLE_FIELDS = {
        "basic_info",
        "preference",
        "skill",
        "last_update_time",
    }

    async def update_user_info_(self, role_id: str, info_dict: dict) -> None:

        # info_dict = self._validate_info_dict(info_dict) or {}

        # 2️⃣ 清洗输入（核心）
        cleaned = {
            k: v for k, v in info_dict.items()
            if k in self._UPDATABLE_FIELDS and v not in (None, "", {})
        }

        if not cleaned:
            return None

        # 3️⃣ 自动时间
        cleaned["last_update_time"] = "datetime()"

        # 4️⃣ 动态 SET
        set_clause = ", ".join(
            f"ui.{k} = ${k}" if k != "last_update_time"
            else "ui.last_update_time = datetime()"
            for k in cleaned
        )

        query = f"""
        MERGE (ui:UserInfoNode {{role_id: $role_id}})

        ON CREATE SET
            ui.user_info_uuid = randomUUID(),
            ui.create_time = datetime()

        SET {set_clause}

        RETURN ui.user_info_uuid AS user_info_uuid
        """

        params = {
            "role_id": role_id,
            **cleaned,
        }

        result = await self.manager.execute_write(query, params)

        return result[0]["user_info_uuid"]

if __name__ == '__main__':
    ui = UserInfoStore()

    import asyncio

    info_dict = {'preference': ' ', 'skill': ' ', 'basic_info':' '}
    asyncio.run(ui.update_user_info_("conv-91", info_dict))
    # asyncio.run(ui.uniq_user_info())

    role_id = "mock_user_001"
    # result = asyncio.run(ui.query_by_role_id(role_id))
    # print(result)
    # print(type(result))

    """
    当 user_info_node 不存在时， 输出 None

    当存在时，
    {'user_info_uuid': 'fee24a3c-1f97-4f66-85bd-a406caeaac5b', 'role_id': 'mock_user_001', 'basic_info': '用户居住在北京，从事程序员工作，年龄在31到35岁之间，目前的近况是“我想体验世界的每一面”。', 'preference': '用户希望寻找兴趣搭子和运动搭子，最热衷的兴趣是音乐，同时也喜欢游泳和做饭/烘焙，愿意讨论听的歌和线上娱乐，并倾向于匹配技能互补、生活节奏相近、和自己不太一样但有趣、以及兴趣相近的人。', 'skill': '用户具备绘画和乐器/唱歌相关的技能，并希望有人教她进一步学习或提升这些技能。', 'create_time': neo4j.time.DateTime(2026, 5, 11, 15, 32, 3, 147623000), 'last_update_time': neo4j.time.DateTime(2026, 5, 11, 15, 49, 38, 21272000)}
    <class 'dict'>
    """