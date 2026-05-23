# neo4j-mcp

Minimal JSON-RPC style MCP mock server for user interest graph operations. It uses an in-memory graph by default.

## Start

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\mcp-servers\neo4j-mcp
python server.py
```

Default port: `7004`.

Config fields:

- `PORT`: HTTP port, default `7004`
- `NEO4J_MOCK_MODE`: default `true`
- `NEO4J_URI`: default `bolt://127.0.0.1:7687`
- `NEO4J_DATABASE`: default `neo4j`

## Tools

### query_user_interest_graph

Request arguments:

```json
{"user_id": "default-user"}
```

Response output:

```json
{"user_id": "default-user", "topics": [{"name": "AI", "weight": 0.91}], "mock": true}
```

### update_user_interest_graph

Request arguments:

```json
{"user_id": "default-user", "topics": [{"name": "workflow", "weight": 0.2}]}
```

Response output:

```json
{"updated": true, "user_id": "default-user", "topics": [{"name": "AI", "weight": 0.91}], "mock": true}
```

### get_related_topics

Request arguments:

```json
{"topic": "AI", "limit": 3}
```

Response output:

```json
{"topic": "AI", "topics": [{"name": "agents", "score": 0.9}], "mock": true}
```

### explain_recommendation

Request arguments:

```json
{"user_id": "default-user", "article": {"title": "AI workflow"}}
```

Response output:

```json
{"user_id": "default-user", "score": 0.91, "reasons": ["matched user topic `AI`"], "mock": true}
```
