"""
向后兼容桥接 — 核心逻辑已迁移至 app.common.indexing.neo4j_schema

请优先使用:
    from app.common.indexing.neo4j_schema import init_time_indexes, init_fulltext_indexes
"""

from app.common.indexing.neo4j_schema import (
    TIME_INDEXES,
    init_fulltext_indexes,
    init_time_indexes,
)

__all__ = ["TIME_INDEXES", "init_time_indexes", "init_fulltext_indexes"]
