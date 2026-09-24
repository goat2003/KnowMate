from typing import Any, Dict, List, Optional

from uuid import uuid4
# Neo4jManager：单例模式的异步连接管理器，全局共享连接池
from app.common.manager.neo4j_manager import Neo4jManager
from datetime import datetime, timedelta
from app.common.client.embedding_client import EmbeddingClient
import logging
from app.memory.tools_service import ToolService
import app.common.config.parameters_config as parameters_config

logger = logging.getLogger(__name__)

class FactStore:
    def __init__(self):
        self.manager = Neo4jManager.get_instance()
        self.tool_service = ToolService()
        self.embedding_client = EmbeddingClient()

    # =========================================================================
    # Schema 初始化
    # =========================================================================
    async def ensure_schema(self) -> None:
        """创建 Neo4j 约束与索引（幂等：IF NOT EXISTS 保证重复执行不报错）。

        约束 = 数据完整性保证（唯一性）+ MERGE 定位依据
        索引 = 查询加速（大用户量下 ddl 过滤 / role+time 排序必须走索引）
        """
        statements = [
            # ── 唯一约束（MERGE 的定位键） ──
            # uuid 本来就是唯一的，不需要再单独创建实体节点和事实节点的唯一约束了
            # "CREATE CONSTRAINT original_fact_uuid_unique IF NOT EXISTS FOR (o:OriginalFact) REQUIRE o.ori_fact_uuid IS UNIQUE",
            # "CREATE CONSTRAINT derived_fact_uuid_unique IF NOT EXISTS FOR (d:DerivedFact) REQUIRE d.dev_uuid IS UNIQUE",
            # "CREATE CONSTRAINT entity_uuid_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_uuid IS UNIQUE",
            # 联合唯一：同一用户下，同名同类型同语义实体只保留一个
            "CREATE CONSTRAINT entity_role_name_type_semantic_unique IF NOT EXISTS FOR (e:Entity) REQUIRE (e.role_id, e.name, e.type,e.semantic) IS UNIQUE",
            # ── 普通索引（查询加速） ──
            "CREATE INDEX original_fact_role_idx IF NOT EXISTS FOR (o:OriginalFact) ON (o.role_id, o.create_time)",
            "CREATE INDEX derived_fact_ddl_idx IF NOT EXISTS FOR (d:DerivedFact) ON (d.role_id, d.ddl)",
            "CREATE INDEX entity_role_name_idx IF NOT EXISTS FOR (e:Entity) ON (e.role_id, e.name, e.type,e.semantic)",
        ]
        for statement in statements:
            await self.manager.execute_write(statement, {})  # execute_write 保证 schema 变更立即生效


    # ======================== ORIGINAL_FACT ======================
    # 创建节点和建立 HAS_FACT 边 两个操作合并在一起
    async def create_original_fact(
            self,
            chunk_uuid: str,
            role_id: str,
            summary: str,  # LLM 生成的 topic 摘要（Milvus 向量化用）
            # content: str,   # 用于收集chunk_summary 的原文
            importance: float,  # 初始=0，由 UserProfile 逐条评分后写入
            confidence: int=1,  # 初始=1，create 后由 update_original_fact_confidence 更新
            used_count: int=0,  # 初始=0，被检索消费时自增
            history_feedback: float=0.0,  # 预留字段，始终 0.0
    ) -> str|None :
        """
        创建 original_fact 节点
        每一个 original_fact 节点与 chunk 节点相连

        Args:
            ori_fact_uuid: OriginalFact节点UUID
            role_id: 用户ID
            summary: LLM 生成的 topic 摘要
            content:  chunk_summary 的原文
            confidence: chunk 来源个数
            importance: 由 LLM 判断的该事件(topic)的重要性
            used_count: 被检索消费时自增
            create_time: 节点创建时间
            history_feedback: 用户的反馈值

        Returns:
            str: original_fact 节点的 UUID
        """

        query = """
            MATCH (ch:ChunkNode {chunk_uuid: $chunk_uuid})
            
            CREATE (o:OriginalFact)
            SET
                o.role_id = $role_id,
                o.ori_fact_uuid = $ori_fact_uuid,
                o.create_time = $current_time,
                o.last_update_time = $current_time,
                o.last_used_time = $current_time,
                o.summary = $summary,
                o.confidence = $confidence,
                o.importance = $importance,
                o.used_count = $used_count,
                o.history_feedback = $history_feedback

            WITH o
            MATCH (ch:ChunkNode {chunk_uuid: $chunk_uuid})

            MERGE (ch)-[:HAS_FACT]->(o)

            RETURN o.ori_fact_uuid AS ori_fact_uuid
            """

        params = {
            "chunk_uuid":chunk_uuid,
            "role_id": role_id,
            "ori_fact_uuid": str(uuid4()),
            "current_time": datetime.now(),
            # "content": content,
            "summary": summary,
            "confidence": int(confidence),          # 强制 int 防止 float 写入
            "importance": float(importance),        # 强制 float 保持字段类型一致
            "used_count": int(used_count),
            "history_feedback": float(history_feedback),
        }

        result = await self.manager.execute_write(query, params)

        if not result:
            logger.warning(
                f"ChunkNode not found: {chunk_uuid}"
            )
            return None  # 当chunk_uuid 异常/未存在时

        return result[0]["ori_fact_uuid"] if result else None


    # 更新节点和建立 HAS_FACT 边 两个操作合并在一起
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
    async def update_original_fact_(
            self,
            chunk_uuid: str,
            ori_fact_uuid: str,
            **fields,
    ) -> None:
        """
        更新 OriginalFact 节点指定字段。

        Example:
            await repo.update_original_fact(
                chunk_uuid=chunk_uuid,
                ori_fact_uuid=ori_fact_uuid,
                summary=summary,
                confidence=confidence,
            )
        """

        if not fields:
            return

        invalid_fields = set(fields) - self._UPDATABLE_FIELDS
        if invalid_fields:
            logger.warning(f"Unsupported fields: {invalid_fields}. "
                f"Allowed fields: {self._UPDATABLE_FIELDS}")
            return

        set_clause = ", ".join(
            f"o.{field} = ${field}"
            for field in fields
        )

        print(set_clause)

        query = f"""
        MATCH (ch:ChunkNode {{
            chunk_uuid: $chunk_uuid
        }})
        
        MATCH (o:OriginalFact {{
            ori_fact_uuid: $ori_fact_uuid
        }})
        
        SET {set_clause}
        
        MERGE (ch)-[:HAS_FACT]->(o)
        
        RETURN o.ori_fact_uuid AS ori_fact_uuid
        """

        params = {
            "chunk_uuid": chunk_uuid,
            "ori_fact_uuid": ori_fact_uuid,
            **fields,
        }

        await self.manager.execute_write(query, params)


    async def update_original_fact(
            self,
            chunk_uuid: str,
            ori_fact_uuid: str,
            **fields,
    ) -> None:
        return await self.tool_service.safe_retry(
            func=self.update_original_fact_,
            chunk_uuid=chunk_uuid,
            ori_fact_uuid=ori_fact_uuid,
            **fields,
        )

    async def get_ori_fact_by_uuid(
            self,
            ori_fact_uuid: str,
            field_names: list[str]
    ) -> dict | None:

        # 1. 安全校验
        invalid_fields = [
            f for f in field_names
            if f not in self._UPDATABLE_FIELDS
        ]

        if invalid_fields:
            logger.warning(
                f"Unsupported fields: {invalid_fields}"
            )
            return None

        # 2. 动态拼 RETURN
        return_fields = ", ".join(
            [f"o.{f} AS {f}" for f in field_names]
        )

        query = f"""
        MATCH (o:OriginalFact {{ori_fact_uuid: $uuid}})
        RETURN {return_fields}
        """

        params = {
            "uuid": ori_fact_uuid
        }

        rows = await self.manager.execute_query(query, params)

        if not rows:
            return None

        return rows[0]


    # 通过指定 ori_fact 节点，顺着边获取所有与之相连的 chunk_summary
    async def get_original_fact_summary(self, ori_fact_uuid: str) -> str | None:
        """
        通过 OriginalFact UUID 反向获取所有 ChunkNode.summary，并拼接成完整字符串
        """

        query = """
            MATCH (o:OriginalFact {ori_fact_uuid: $ori_fact_uuid})
            MATCH (c:ChunkNode)-[:HAS_FACT]->(o)
            WITH c.summary AS summary
            WHERE summary IS NOT NULL
            RETURN collect(summary) AS summaries
        """

        params = {
            "ori_fact_uuid": ori_fact_uuid
        }

        result = await self.manager.execute_query(query, params)

        if not result:
            return None

        summaries = result[0].get("summaries", [])

        if not summaries:
            return ""

        # 可选：保证顺序稳定（如果你有时间字段建议排序）
        final_text = " ".join(summaries).strip()

        return final_text


    """touch_original_fact_used"""
    # async def touch_original_fact_used(self, role_id: str, ori_fact_uuid: str, used_time) -> None:
    #     """记录 OriFact 被检索消费：更新 last_used_time 且 used_count 自增 1。"""
    #     query = """
    #     MATCH (o:OriginalFact {role_id: $role_id, ori_fact_uuid: $ori_fact_uuid})
    #     SET
    #         o.last_used_time = $used_time,
    #         o.used_count = coalesce(o.used_count, 0) + 1
    #     """
    #     await self.manager.execute_write(
    #         query,
    #         {"role_id": role_id, "ori_fact_uuid": ori_fact_uuid, "used_time": used_time},
    #     )

    # 仅连接 chunk-ori_fact
    async def link_chunk_to_fact(
            self,
            chunk_uuid: str,
            ori_fact_uuid: str,
    ) -> None:
        query = """
        MATCH (ch:ChunkNode {chunk_uuid: $chunk_uuid})
        MATCH (o:OriginalFact {ori_fact_uuid: $ori_fact_uuid})
        MERGE (ch)-[:HAS_FACT]->(o)
        """

        params = {
            "chunk_uuid": chunk_uuid,
            "ori_fact_uuid": ori_fact_uuid,
        }

        await self.manager.execute_write(query, params)

    # ========================= DERIVED_FACT =====================
    # 创建节点和建立 DERIVED_FROM 边合并在一起

    async def create_derived_fact(
            self,
            chunk_uuid: str,
            role_id: str,
            summary: str,  # 派生结论文本
            confidence: int=1,  # 由 update_derived_fact_confidence_from_originals 重算
            status: int=0,  # 初始值为0，由 update_derived_fact_status_ddl 重算
            weight: float=0.0,  # 预留，始终 0.0
    ) -> str | None:
        """
        创建 derived_fact 节点
        每一个 derived_fact 节点与  original_fact 节点相连

        Args:
            dev_uuid: DerivedFact节点UUID
            role_id: 用户ID
            summary: LLM 生成的 topic 摘要
            confidence: chunk 来源个数
            status: 稳定性 状态  1->stable  0->unstable
            create_time: 节点创建时间
            weight: 权重 暂时不用
            ddl: 在不稳定状态下达到一定时间执行节点清除  90天期限
            last_update_time: 最后一次更新时间 初始值为创建时间

        Returns:
            str: derived_fact 节点的 UUID
        """

        query = """
            MATCH (ch:ChunkNode {chunk_uuid: $chunk_uuid})

            CREATE (d:DerivedFact)
            SET
                d.role_id = $role_id,
                d.dev_uuid = $dev_uuid,
                d.create_time = $current_time,
                d.last_update_time = $current_time,
                d.summary = $summary,
                d.confidence = $confidence,
                d.status = $status,
                d.weight = $weight,
                d.ddl = $ddl

            WITH d
            MATCH (ch:ChunkNode {chunk_uuid: $chunk_uuid})

            MERGE (ch)-[:DERIVED_FROM]->(d)

            RETURN d.dev_uuid AS dev_uuid
            """

        # 获取时间
        current_time = datetime.now()
        future_time = current_time + timedelta(days=90)

        params = {
            "chunk_uuid": chunk_uuid,
            "role_id": role_id,
            "dev_uuid": str(uuid4()),
            "summary": summary,
            "confidence": int(confidence),
            "status": int(status),
            "weight": float(weight),
            "ddl": future_time,
            "current_time": current_time
        }

        result = await self.manager.execute_write(query, params)

        if not result:
            logger.warning(
                f"OriginalFact not found: {chunk_uuid}"
            )
            return None  # 当chunk_uuid 异常/未存在时

        return result[0]["dev_uuid"] if result else None


    _UPDATABLE_FIELDS_DEV = {
        "dev_uuid",
        "role_id",
        "summary",
        "confidence",
        "status",
        "create_time",
        "last_update_time",
        "weight",
        "ddl",
    }
    async def update_derived_fact_(
            self,
            chunk_uuid: str,
            dev_uuid: str,
            **fields,
    ) -> None:
        """
        更新 DerivedFact 节点指定字段。

        Example:
            await repo.update_derived_fact_(
                chunk_uuid=chunk_uuid,
                dev_uuid=dev_uuid,
                summary=summary,
                confidence=confidence
            )
        """

        if not fields:
            return

        invalid_fields = set(fields) - self._UPDATABLE_FIELDS_DEV
        if invalid_fields:
            print(f"Unsupported fields: {invalid_fields}. "
                  f"Allowed fields: {self._UPDATABLE_FIELDS_DEV}")
            return

        set_clause = ", ".join(
            f"d.{field} = ${field}"
            for field in fields
        )

        print(set_clause)

        query = f"""
        MATCH (ch:ChunkNode {{
            chunk_uuid: $chunk_uuid
        }})

        MATCH (d:DerivedFact {{
            dev_uuid: $dev_uuid
        }})

        SET {set_clause}

        MERGE (ch)-[:DERIVED_FROM]->(d)

        RETURN d.dev_uuid AS dev_uuid
        """

        params = {
            "chunk_uuid": chunk_uuid,
            "dev_uuid": dev_uuid,
            **fields,
        }

        await self.manager.execute_write(query, params)

    async def update_derived_fact(
            self,
            chunk_uuid: str,
            dev_uuid: str,
            **fields,
    ) -> None:
        return await self.tool_service.safe_retry(
            func=self.update_derived_fact_,
            chunk_uuid=chunk_uuid,
            dev_uuid=dev_uuid,
            **fields,
        )


    async def get_dev_fact_by_uuid(
            self,
            dev_uuid: str,
            field_names: list[str]
    ) -> dict | None:

        # 1. 字段白名单校验
        invalid_fields = [
            f for f in field_names
            if f not in self._UPDATABLE_FIELDS_DEV
        ]

        if invalid_fields:
            logger.warning(
                f"Unsupported fields: {invalid_fields}"
            )
            return None

        # 2. 动态拼 Cypher RETURN
        return_fields = ", ".join(
            [f"d.{f} AS {f}" for f in field_names]
        )

        query = f"""
        MATCH (d:DerivedFact {{dev_uuid: $dev_uuid}})
        RETURN {return_fields}
        """

        params = {
            "dev_uuid": dev_uuid
        }

        rows = await self.manager.execute_query(query, params)

        if not rows:
            return None

        return rows[0]


    async def touch_derived_fact_used(self, role_id: str, dev_uuid: str, used_time) -> None:
        """记录 DevFact 被检索消费：仅更新 last_used_time（无 used_count）。"""
        query = """
        MATCH (d:DerivedFact {role_id: $role_id, dev_uuid: $dev_uuid})
        SET d.last_used_time = $used_time
        """
        await self.manager.execute_write(
            query, {"role_id": role_id, "dev_uuid": dev_uuid, "used_time": used_time},
        )

    # 通过指定指定时间以及条件status=0 删除 ddl 小于该指定时间的节点
    async def delete_expired_derived_facts_by_status(
            self,
            now_time: datetime,
            status: int = 0,
            limit: int = 200,
    ) -> list[str] | None:
        """
        删除 ddl < now_time 且 status=0 的 DerivedFact
        """
        query = """
        MATCH (d:DerivedFact {status: $status})
        WHERE d.ddl < $now_time

        WITH d
        ORDER BY d.ddl ASC
        LIMIT $limit

        WITH collect(d.dev_uuid) AS uuids, collect(d) AS nodes

        FOREACH (n IN nodes | DETACH DELETE n)

        RETURN uuids
        """

        rows = await self.manager.execute_query(
            query,
            {
                "status": status,
                "now_time": now_time,
                "limit": limit,
            },
        )

        if not rows:
            return None

        uuids = rows[0].get("uuids") or []
        uuids = [u for u in uuids if u]

        return uuids


    # =================== ENTITY_NODE ====================
    async def create_entity_(
            self,
            role_id: str,
            chunk_uuid: str,  # 关联的原始事实 UUID（必传，作为关系定位依据）
            name: str,           # 实体名，如"北京"
            entity_type: str,           # 实体类型，如"地点"（5种中文类型之一）
            semantic: str,       # 实体语义补充，如"地点-常去"
    ) -> str:
        """
        新版 实体节点创建不再进行融合

        因此只需匹配是否满足了唯一约束
        """

        """
        仅创建实体节点 + 关系，不做语义融合。
        依赖唯一约束：
        (role_id, name, type, semantic)
        """

        query = """
            MATCH (ch:ChunkNode {chunk_uuid: $chunk_uuid})

            MERGE (e:Entity {
                role_id: $role_id,
                name: $name,
                type: $type,
                semantic: $semantic
            })
            ON CREATE SET
                e.entity_uuid = $entity_uuid

            MERGE (ch)-[:HAS_ENTITY]->(e)

            RETURN e.entity_uuid AS entity_uuid
            """

        rows = await self.manager.execute_query(
            query,
            {
                "chunk_uuid": chunk_uuid,
                "entity_uuid": str(uuid4()),
                "role_id": role_id,
                "name": name,
                "type": entity_type,
                "semantic": semantic,
            },
        )

        return rows[0]["entity_uuid"] if rows else None


    _UPDATABLE_FIELDS_ENTITY = {
        "entity_uuid",
        "role_id",
        "name",
        "type",
        "semantic",
    }
    async def get_entity_by_uuid(
            self,
            entity_uuid: str,
            field_names: list[str]
    ) -> dict | None:

        # 1. 白名单校验（防止任意字段注入）
        invalid_fields = [
            f for f in field_names
            if f not in self._UPDATABLE_FIELDS_ENTITY
        ]

        if invalid_fields:
            logger.warning(
                f"Unsupported fields: {invalid_fields}"
            )
            return None

        # 2. 动态拼 RETURN
        return_fields = ", ".join(
            [f"e.{f} AS {f}" for f in field_names]
        )

        query = f"""
        MATCH (e:Entity {{entity_uuid: $entity_uuid}})
        RETURN {return_fields}
        """

        params = {
            "entity_uuid": entity_uuid
        }

        rows = await self.manager.execute_query(query, params)

        if not rows:
            return None

        return rows[0]


    async def get_full_entity_by_uuid(
            self,
            entity_uuid: str,
    ):
        query = """
        MATCH (e:Entity {entity_uuid: $entity_uuid})
        RETURN e
        """
        params = {
            "entity_uuid": entity_uuid
        }
        rows = await self.manager.execute_query(
            query,
            params,
        )

        if not rows:
            return None

        return rows[0].get("e")



    async def link_entity_to_chunk_(
            self,
            role_id: str,
            chunk_uuid: str,
            entity_uuid: str,
    ) -> bool:
        """
        通过 entity_uuid 找到实体节点，并与 chunk_uuid 对应的 ChunkNode 建立关系
        MERGE (ch)-[:HAS_ENTITY]->(e)
        """

        query = """
            MATCH (ch:ChunkNode {chunk_uuid: $chunk_uuid})
            MATCH (e:Entity {entity_uuid: $entity_uuid, role_id: $role_id})

            MERGE (ch)-[:HAS_ENTITY]->(e)

            RETURN e.entity_uuid AS entity_uuid
        """

        rows = await self.manager.execute_query(
            query,
            {
                "chunk_uuid": chunk_uuid,
                "entity_uuid": entity_uuid,
                "role_id": role_id,
            },
        )

        return bool(rows)

    async def create_entity_relates_edges(
            self,
            entity_uuids: list[str],
    ) -> int:
        """
        将多个 entity 节点两两相连，关系：RELATES_TO
        """

        query = """
            UNWIND $uuids AS id1
            UNWIND $uuids AS id2

            WITH id1, id2
            WHERE id1 < id2   // 防止重复 & 自连

            MATCH (e1:Entity {entity_uuid: id1})
            MATCH (e2:Entity {entity_uuid: id2})

            MERGE (e1)-[:RELATES_TO]-(e2)

            RETURN count(*) AS cnt
        """

        rows = await self.manager.execute_query(
            query,
            {
                "uuids": entity_uuids
            },
        )

        return rows[0]["cnt"] if rows else 0

        # =========================================================================
        # 重要事实检索
        # =========================================================================

        # 有条件获取fact节点
        # 筛选 importance > 0.6  或更高的节点 + 加权计算 + 排序
        # 限定标签：DerivedFact 或 OriginalFact
        # 过滤：importance > 0.6
        # 计算加权值：importance * w1 + confidence * w2
        # 排序
        # 取 top-k
        # 返回 content

    async def get_top_k_facts_by_role(
            self,
            role_id: str,
            top_k: int,  # 选取前k个重要事件
            w_importance: float,
            w_confidence: float,
            importance_val: float,
    ) -> List[Dict]:
        query = """
           MATCH (n:OriginalFact)
           WHERE n.role_id = $role_id
             AND n.importance > $importance_val

           WITH n,
            (
               n.importance * $w_importance
               +
               (
                   log(1 + n.confidence)
                   /
                   (1 + log(1 + n.confidence))
               ) * $w_confidence
            ) AS score

           ORDER BY score DESC
           LIMIT $top_k

           RETURN n.summary AS content, score
           """

        params = {
            "role_id": role_id,
            "top_k": top_k,
            "w_importance": parameters_config.W_IMPORTANCE,
            "w_confidence": parameters_config.W_CONFIDENCE,
            "importance_val": importance_val
        }
        result = await self.manager.execute_query(query, params)  # 读操作用 execute_query
        return result if result else []

    async def get_chunk_relation_status(
            self,
            chunk_uuid: str,
    ) -> dict:
        """
        判断 Chunk 是否拥有 HAS_FACT / HAS_ENTITY / DERIVED_FROM 关系
        """

        query = """
            MATCH (ch:ChunkNode {chunk_uuid: $chunk_uuid})

            RETURN
                EXISTS {
                    MATCH (ch)-[:HAS_FACT]->()
                } AS has_fact,

                EXISTS {
                    MATCH (ch)-[:HAS_ENTITY]->()
                } AS has_entity,

                EXISTS {
                    MATCH (ch)-[:DERIVED_FROM]->()
                } AS derived_from
        """

        rows = await self.manager.execute_query(
            query,
            {
                "chunk_uuid": chunk_uuid,
            },
        )

        if not rows:
            return {
                "has_fact": False,
                "has_entity": False,
                "derived_from": False,
            }

        return rows[0]


# ================ 通用 查找边连接节点 =================
import re

class GraphORM:
    """
    Mini Neo4j ORM for KG traversal
    """

    NODE_SCHEMA = {
        "ChunkNode": "chunk_uuid",
        "OriginalFact": "ori_fact_uuid",
        "DerivedFact": "dev_uuid",
        "Entity": "entity_uuid",
    }

    REL_SCHEMA = {
        ("ChunkNode", "OriginalFact"): "HAS_FACT",
        ("OriginalFact", "ChunkNode"): "HAS_FACT",

        ("ChunkNode", "DerivedFact"): "DERIVED_FROM",
        ("DerivedFact", "ChunkNode"): "DERIVED_FROM",

        ("ChunkNode", "Entity"): "HAS_ENTITY",
        ("Entity", "ChunkNode"): "HAS_ENTITY",

        ("Entity", "Entity"): "RELATES_TO"
    }

    def __init__(self):
        self.manager = Neo4jManager.get_instance()

    # ----------------------------
    # 工具函数
    # ----------------------------
    def _field(self, node_type: str) -> str:
        if node_type not in self.NODE_SCHEMA:
            raise ValueError(f"Unknown node_type: {node_type}")
        return self.NODE_SCHEMA[node_type]

    def _rel(self, source: str, target: str) -> str:
        key = (source, target)
        if key not in self.REL_SCHEMA:
            raise ValueError(f"Unknown relation: {source} -> {target}")
        return self.REL_SCHEMA[key]

    def _safe(self, value: str):
        if not re.match(r"^[a-zA-Z0-9_]+$", value):
            raise ValueError(f"Unsafe input: {value}")
        return value

    def both(self, target_type: str):
        self._direction = None  # 显式无向
        self._target_type = target_type
        return self

    # ----------------------------
    # 主查询 API
    # ----------------------------
    def find(
            self,
            node_type: str,
            node_uuid: str
    ):
        self._node_type = node_type
        self._node_uuid = node_uuid
        self._direction = None
        self._target_type = None
        self._rel_type = None
        return self

    def out(self, target_type: str):
        self._direction = "out"
        self._target_type = target_type
        return self

    def in_(self, target_type: str):
        self._direction = "in"
        self._target_type = target_type
        return self

    def rel(self, rel_type: str):
        self._rel_type = rel_type
        return self

    # ----------------------------
    # 执行
    # ----------------------------
    async def run(self) -> list[str]:
        if not self._target_type:
            raise ValueError(
                "Missing target_type: call out(<type>) or in_(<type>) before run()"
            )
        source_field = self._field(self._node_type)
        target_field = self._field(self._target_type)

        source_field = self._safe(source_field)
        target_field = self._safe(target_field)

        rel_type = self._rel_type
        if not rel_type:
            rel_type = self._rel(self._node_type, self._target_type)

        rel_type = self._safe(rel_type)

        # direction
        if self._direction == "out":
            pattern = f"(n)-[:{rel_type}]->(m)"
        elif self._direction == "in":
            pattern = f"(n)<-[:{rel_type}]-(m)"
        else:
            pattern = f"(n)-[:{rel_type}]-(m)"

        # query = f"""
        #     MATCH (n {{{source_field}: $node_uuid}})
        #     MATCH {pattern}
        #     RETURN m.{target_field} AS uuid
        # """

        query = f"""
        MATCH (n:{self._node_type} {{{source_field}: $node_uuid}})-[:{rel_type}]-(m:{self._target_type})
        RETURN m.{target_field} AS uuid
        """

        result = await self.manager.execute_query(
            query,
            {"node_uuid": self._node_uuid}
        )

        return [r["uuid"] for r in result if r.get("uuid")]



    # 调用方式
    #
    # 🔹 1. Chunk → OriginalFact
    #
    # uuids = await graph.find(
    #     "ChunkNode",
    #     chunk_uuid
    # ).out(
    #     "OriginalFact"
    # ).run()
    #
    # 🔹 2. Chunk → DerivedFact
    #
    # uuids = await graph.find(
    #     "ChunkNode",
    #     chunk_uuid
    # ).out(
    #     "DerivedFact"
    # ).run()
    #
    # 🔹 3. Chunk → Entity
    #
    # uuids = await graph.find(
    #     "ChunkNode",
    #     chunk_uuid
    # ).out(
    #     "Entity"
    # ).run()
    #
    # 🔹 4. 反向查询（Fact → Chunk）
    #
    # chunks = await graph.find(
    #     "OriginalFact",
    #     fact_uuid
    # ).in_(
    #     "ChunkNode"
    # ).run()








