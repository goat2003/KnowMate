# MCP Servers MVP

This directory contains standalone Python mock MCP servers. Each server uses a JSON-RPC style HTTP API:

- `GET /health`
- `GET /tools`
- `POST /rpc`
- `POST /call` legacy compatibility wrapper

JSON-RPC call shape:

```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "tools/call",
  "params": {
    "name": "tool_name",
    "arguments": {}
  }
}
```

Default ports:

- `embedding-mcp`: `7001`
- `fetch-mcp`: `7002`
- `milvus-mcp`: `7003`
- `neo4j-mcp`: `7004`

The Python Agent can run without these servers when `MOCK_MCP=true`. Set `MOCK_MCP=false` in `python-agent` to call these mock servers through HTTP JSON-RPC.

Real service replacement points:

- `REAL_EMBEDDING_ENDPOINT`
- `REAL_FETCH_PROXY`
- `MILVUS_URI`
- `MILVUS_COLLECTION`
- `NEO4J_URI`
- `NEO4J_DATABASE`
