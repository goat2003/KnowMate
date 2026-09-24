"""fact_node 的 Neo4j 仓储层。

只负责图数据库读写，不处理任何业务编排。
所有 Cypher 语句收口于此，上层通过 FactPipeline 调用。

"""

import uuid
from typing import Any, Dict, List, Optional

# Neo4jManager：单例模式的异步连接管理器，全局共享连接池
from app.common.manager.neo4j_manager import Neo4jManager
from datetime import datetime

class FactGraphRepository:
    """封装 fact_node 相关的全部图存储操作。"""

    def __init__(self, manager=None):
        # manager 可注入 mock，便于单元测试不依赖真实 Neo4j
        self.manager = manager or Neo4jManager.get_instance()




    # ---------- OriFact 辅助方法 ----------
    _UPDATABLE_FIELDS = {
        "create_time",
        "last_update_time",
        "last_used_time",
        "summary",
        "confidence",
        "importance",
        "used_count",
        "history_feedback",
    }

    async def touch_original_fact_used(self, role_id: str, ori_fact_uuid: str, used_time) -> None:
        """记录 OriFact 被检索消费：更新 last_used_time 且 used_count 自增 1。"""
        query = """
        MATCH (o:OriginalFact {role_id: $role_id, ori_fact_uuid: $ori_fact_uuid})
        SET
            o.last_used_time = $used_time,
            o.used_count = coalesce(o.used_count, 0) + 1
        """
        await self.manager.execute_write(
            query,
            {"role_id": role_id, "ori_fact_uuid": ori_fact_uuid, "used_time": used_time},
        )
