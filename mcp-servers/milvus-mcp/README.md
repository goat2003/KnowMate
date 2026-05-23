# milvus-mcp

Minimal JSON-RPC style MCP mock server for vector memory operations. It uses an in-memory store by default.

## Start

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\mcp-servers\milvus-mcp
python server.py
```

Default port: `7003`.

Config fields:

- `PORT`: HTTP port, default `7003`
- `MILVUS_MOCK_MODE`: default `true`
- `MILVUS_URI`: default `http://127.0.0.1:19530`
- `MILVUS_COLLECTION`: default `knowledge_memory`

## Tools

### insert_memory_vector

Request arguments:

```json
{"id": "m1", "embedding": [0.1, 0.2, 0.3], "metadata": {"topic": "AI"}}
```

Response output:

```json
{"upserted": true, "id": "m1", "count": 1, "mock": true}
```

### search_similar_memory

Request arguments:

```json
{"embedding": [0.1, 0.2, 0.3], "limit": 3}
```

Response output:

```json
{"matches": [{"id": "m1", "score": 1.0, "metadata": {"topic": "AI"}}], "mock": true}
```

### search_related_articles

Request arguments:

```json
{"topic": "AI", "limit": 3}
```

Response output:

```json
{"matches": [{"article_id": "mock-related-1", "title": "AI related article 1", "score": 0.85}], "mock": true}
```

### search_articles

Request arguments:

```json
{"topic": "AI", "limit": 3}
```

Response output:

```json
{"matches": [{"article_id": "mock-related-1", "title": "AI related article 1", "score": 0.85}], "mock": true}
```

### semantic_deduplicate

Request arguments:

```json
{"items": [{"id": "a1", "text": "AI workflow"}, {"id": "a2", "text": "workflow AI"}], "threshold": 0.88}
```

Response output:

```json
{"unique_items": ["a1"], "duplicate_groups": [{"canonical_id": "a1", "duplicate_id": "a2"}], "threshold": 0.88, "mock": true}
```
