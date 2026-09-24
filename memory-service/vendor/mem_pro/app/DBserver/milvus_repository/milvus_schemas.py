from pymilvus import FieldSchema, CollectionSchema, DataType


VECTOR_DIM = 1536


def chunk_schema():
    """chunk collection —— 原始对话片段，含 dia_embedding + summary_embedding 双向量。"""
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="role_id", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="chunk_uuid", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="fact_uuid", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="dia_embedding", dtype=DataType.FLOAT_VECTOR, dim=VECTOR_DIM),
        FieldSchema(name="summary_embedding", dtype=DataType.FLOAT_VECTOR, dim=VECTOR_DIM),
        # FieldSchema(name="chunk_content_index", dtype=DataType.INT64),
    ]
    return CollectionSchema(fields, description="chunk collection")


def ori_fact_schema():
    """ori_fact collection —— 原始事实摘要向量，用于语义检索。"""
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="role_id", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="uuid", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="summary", dtype=DataType.VARCHAR, max_length=4096),
        FieldSchema(name="summary_embedding", dtype=DataType.FLOAT_VECTOR, dim=VECTOR_DIM),
    ]
    return CollectionSchema(fields, description="ori_fact collection")


def dev_fact_schema():
    """dev_fact collection —— 派生事实摘要向量，用于语义检索。"""
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="role_id", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="uuid", dtype=DataType.VARCHAR, max_length=256),
        # FieldSchema(name="chunk_uuid", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="summary", dtype=DataType.VARCHAR, max_length=4096),
        FieldSchema(name="summary_embedding", dtype=DataType.FLOAT_VECTOR, dim=VECTOR_DIM),
        # FieldSchema(name="status", dtype=DataType.INT64),
    ]
    return CollectionSchema(fields, description="derived fact collection")


def semantic_entity_schema():
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="uuid", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="role_id", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="name", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="type", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="semantic", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="semantic_embedding", dtype=DataType.FLOAT_VECTOR, dim=VECTOR_DIM),
    ]
    return CollectionSchema(fields, description="semantic entity collection")


def semantic_fact_edge_schema():
    fields = [
        FieldSchema(name="uuid", dtype=DataType.VARCHAR, max_length=256, is_primary=True),
        FieldSchema(name="role_id", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="source_uuid", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="target_uuid", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="is_valid", dtype=DataType.BOOL),
        FieldSchema(name="fact_embedding", dtype=DataType.FLOAT_VECTOR, dim=VECTOR_DIM),
    ]
    return CollectionSchema(fields, description="semantic fact edge collection")


# collection 名 → (schema 工厂, 向量索引字段列表)
COLLECTION_REGISTRY = {
    "chunk_schema": (chunk_schema, ["dia_embedding", "summary_embedding"]),
    "ori_fact_schema": (ori_fact_schema, ["summary_embedding"]),
    "dev_fact_schema": (dev_fact_schema, ["summary_embedding"]),
    "SemanticEntity": (semantic_entity_schema, ["semantic_embedding"]),
    # SemanticFactEdge is not used by the current retrieval flow.
    # Relationship retrieval uses Neo4j graph/fulltext edges instead.
}
