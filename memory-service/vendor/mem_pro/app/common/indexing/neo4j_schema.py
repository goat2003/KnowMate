"""
Neo4j Schema 初始化 — 所有索引和约束的统一定义

涵盖:
- 情景层约束 (EpisodicNode hash_val 唯一约束)
- 语义事实层索引/约束 (UserEntity, PersonEntity, EntityNode, RELATES_TO)
- 时间字段 RANGE 索引
- 全文 BM25 索引

所有语句幂等 (IF NOT EXISTS)，可安全重复调用。
"""

import logging
from typing import List, Tuple

from app.common.manager.neo4j_manager import Neo4jManager

logger = logging.getLogger(__name__)

# ── 时间字段 RANGE 索引定义 ──
TIME_INDEXES: List[Tuple[str, str]] = [
    (
        "derived_fact_status_ddl",
        "CREATE INDEX derived_fact_status_ddl IF NOT EXISTS "
        "FOR (d:DerivedFact) ON (d.status, d.ddl)"
    ),
]


async def init_fulltext_indexes() -> None:
    """Create fulltext indexes (English-first, CJK optional but not required)."""

    manager = Neo4jManager.get_instance()

    try:
        # =========================
        # 1. Entity fulltext index
        # =========================
        await manager.execute_write(
            """
            CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS
            FOR (n:Entity)
            ON EACH [n.name, n.type, n.semantic, n.role_id]
            OPTIONS {
                indexConfig: {
                    `fulltext.analyzer`: "standard"
                }
            }
            """,
            {},
        )
        logger.info("[Schema] Fulltext index ready: entity_fulltext (standard analyzer)")

        # =========================
        # 2. Fact fulltext index
        # =========================
        await manager.execute_write(
            """
            CREATE FULLTEXT INDEX fact_fulltext IF NOT EXISTS
            FOR ()-[r:RELATES_TO]-()
            ON EACH [r.fact]
            OPTIONS {
                indexConfig: {
                    `fulltext.analyzer`: "standard"
                }
            }
            """,
            {},
        )
        logger.info("[Schema] Fulltext index ready: fact_fulltext (standard analyzer)")

    except Exception as e:
        logger.warning(f"[Schema] Fulltext index creation failed: {e}")


"""_create_fulltext_with_cjk_fallback 注释掉，因为最终运行以英文为主"""
async def _create_fulltext_index(name: str, cypher: str) -> None:
    """Create fulltext index (English-first, no CJK fallback)."""

    manager = Neo4jManager.get_instance()

    try:
        await manager.execute_write(cypher, {})
        logger.info(f"[Schema] Fulltext index ready: {name}")
    except Exception as e:
        logger.warning(f"[Schema] Fulltext index failed: {name}, error: {e}")


async def init_retrieval_indexes() -> None:
    """BM25 + structured retrieval indexes (production design)."""

    manager = Neo4jManager.get_instance()

    try:
        # ======================================================
        # 1. Chunk BM25 (dialogue / memory entry)
        # ======================================================
        await manager.execute_write(
            """
            CREATE FULLTEXT INDEX chunk_summary_fulltext IF NOT EXISTS
            FOR (c:ChunkNode)
            ON EACH [c.summary]
            OPTIONS {
                indexConfig: {
                    `fulltext.analyzer`: "standard"
                }
            }
            """,
            {},
        )

        # ======================================================
        # 2. OriginalFact BM25 (memory layer)
        # ======================================================
        await manager.execute_write(
            """
            CREATE FULLTEXT INDEX original_fact_summary_fulltext IF NOT EXISTS
            FOR (o:OriginalFact)
            ON EACH [o.summary]
            OPTIONS {
                indexConfig: {
                    `fulltext.analyzer`: "standard"
                }
            }
            """,
            {},
        )

        # ======================================================
        # 3. DerivedFact BM25 (reasoning layer)
        # ======================================================
        await manager.execute_write(
            """
            CREATE FULLTEXT INDEX derived_fact_fulltext IF NOT EXISTS
            FOR (d:DerivedFact)
            ON EACH [d.summary]
            OPTIONS {
                indexConfig: {
                    `fulltext.analyzer`: "standard"
                }
            }
            """,
            {},
        )

        # ======================================================
        # 4. Entity BM25 (entity retrieval)
        # ======================================================
        await manager.execute_write(
            """
            CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS
            FOR (e:Entity)
            ON EACH [e.name]
            OPTIONS {
                indexConfig: {
                    `fulltext.analyzer`: "standard"
                }
            }
            """,
            {},
        )

        # ======================================================
        # 5. RELATES_TO BM25 (graph semantic edges)
        # ======================================================
        await manager.execute_write(
            """
            CREATE FULLTEXT INDEX fact_edge_fulltext IF NOT EXISTS
            FOR ()-[r:RELATES_TO]-()
            ON EACH [r.fact]
            OPTIONS {
                indexConfig: {
                    `fulltext.analyzer`: "standard"
                }
            }
            """,
            {},
        )

        # ======================================================
        # 6. Chunk lookup index (critical)
        # ======================================================
        await manager.execute_write(
            """
            CREATE INDEX chunk_lookup_idx IF NOT EXISTS
            FOR (c:ChunkNode)
            ON (c.role_id, c.chunk_uuid)
            """,
            {},
        )

        # ======================================================
        # 7. DerivedFact time index (ONLY time-driven case)
        # ======================================================
        await manager.execute_write(
            """
            CREATE INDEX derived_fact_status_ddl_idx IF NOT EXISTS
            FOR (d:DerivedFact)
            ON (d.status, d.ddl)
            """,
            {},
        )

        # ======================================================
        # 8. Entity structured lookup index
        # ======================================================
        await manager.execute_write(
            """
            CREATE INDEX entity_lookup_idx IF NOT EXISTS
            FOR (e:Entity)
            ON (e.role_id, e.name, e.type, e.semantic)
            """,
            {},
        )

        logger.info("[Schema] retrieval indexes initialized (BM25 + Graph hybrid)")

    except Exception as e:
        logger.warning(f"[Schema] retrieval index init failed: {e}")


async def init_all_neo4j_schema() -> None:
    """一站式创建所有 Neo4j 索引和约束"""
    await init_fulltext_indexes()
    await init_retrieval_indexes()
    logger.info("[Schema] 全部 Neo4j Schema 初始化完成")
