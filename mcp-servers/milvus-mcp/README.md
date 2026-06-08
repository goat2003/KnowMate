# milvus-mcp

Tools:

- `insert_memory_vector`
- `batch_insert_memory_vectors`
- `search_similar_memory`
- `search_related_articles`
- `search_articles`
- `delete_memory_vectors`
- `semantic_deduplicate`

`MILVUS_PROVIDER=memory` uses an in-process vector store.
`MILVUS_PROVIDER=milvus` uses PyMilvus and creates or validates
`user_memory_vectors`.

Writes use stable IDs and upsert semantics. Searches and deletes accept only
structured metadata filters with allowlisted `eq`, `in`, `gte`, and `lte`
operators. Raw Milvus filter expressions are not accepted.

Vector dimensions must match exactly. An incompatible existing collection is
reported as unhealthy and is never automatically dropped or rebuilt.
