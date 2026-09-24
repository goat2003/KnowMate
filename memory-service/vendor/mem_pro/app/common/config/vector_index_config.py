"""
向量索引配置

统一管理所有向量索引的名称和配置，避免硬编码。
"""

from typing import Dict, Any


class VectorIndexConfig:
    """
    向量索引配置类

    定义所有向量索引的名称和参数，确保全局一致性。
    """

    # ==================== 索引名称 ====================

    # 情景记忆层
    EPISODIC_CONTENT = "episodic_embedding"
    SUMMARY_CONTENT = "summary_embedding"

    # 语义事实层
    ENTITY_NAME = "entity_name_index"

    # 稳定语义层
    STABLE_EDGE_DESCRIPTION = "stable_edge_description_embedding"

    # ==================== 索引配置 ====================

    @classmethod
    def get_index_config(cls, index_name: str) -> Dict[str, Any]:
        """
        获取索引配置

        Args:
            index_name: 索引名称

        Returns:
            Dict[str, Any]: 索引配置
        """
        configs = {
            cls.EPISODIC_CONTENT: {
                "label": "EpisodicNode",
                "property": "embedding",
                "dimensions": 1024,
                "similarity": "cosine"
            },
            cls.SUMMARY_CONTENT: {
                "label": "SummaryNode",
                "property": "embedding",
                "dimensions": 1024,
                "similarity": "cosine"
            },
            cls.ENTITY_NAME: {
                "label": "EntityNode",
                "property": "name_embedding",
                "dimensions": 1024,
                "similarity": "cosine"
            },
            cls.STABLE_EDGE_DESCRIPTION: {
                "label": "StableAttributeEdge",
                "property": "description_embedding",
                "dimensions": 1024,
                "similarity": "cosine"
            }
        }

        return configs.get(index_name, {})

    @classmethod
    def get_all_indexes(cls) -> Dict[str, Dict[str, Any]]:
        """
        获取所有索引配置

        Returns:
            Dict[str, Dict[str, Any]]: 所有索引配置
        """
        return {
            cls.EPISODIC_CONTENT: cls.get_index_config(cls.EPISODIC_CONTENT),
            cls.SUMMARY_CONTENT: cls.get_index_config(cls.SUMMARY_CONTENT),
            cls.ENTITY_NAME: cls.get_index_config(cls.ENTITY_NAME),
            cls.STABLE_EDGE_DESCRIPTION: cls.get_index_config(cls.STABLE_EDGE_DESCRIPTION)
        }


class ThresholdConfig:
    """
    阈值配置类

    定义系统中使用的各种阈值参数。
    """

    # 实体对齐阈值
    ENTITY_SIMILARITY = 0.92

    # 稳定层置信度阈值
    STABLE_CONFIDENCE_MIN = 0.5

    # 事实融合阈值
    FACT_SIMILARITY = 0.85

    # 检索结果数量
    RETRIEVAL_TOP_K = 5


# 导出配置实例
vector_index_config = VectorIndexConfig()
threshold_config = ThresholdConfig()











