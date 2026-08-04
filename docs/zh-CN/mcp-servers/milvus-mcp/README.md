# milvus-mcp 中文说明

> 原文镜像：`mcp-servers/milvus-mcp/README.md`

Tools：

- `insert_memory_vector`
- `batch_insert_memory_vectors`
- `search_similar_memory`
- `search_related_articles`
- `search_articles`
- `delete_memory_vectors`
- `semantic_deduplicate`

`MILVUS_PROVIDER=memory` 使用进程内向量存储。`MILVUS_PROVIDER=milvus` 使用 PyMilvus，并创建或校验 `user_memory_vectors`。

写入使用稳定 ID 和 upsert 语义。搜索和删除只接受结构化 metadata filters，允许的操作符为 `eq`、`in`、`gte` 和 `lte`。不接受原始 Milvus filter expressions。

向量维度必须精确匹配。不兼容的现有 collection 会被报告为 unhealthy，系统不会自动 drop 或 rebuild。
