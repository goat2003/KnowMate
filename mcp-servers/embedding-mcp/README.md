# embedding-mcp

Minimal JSON-RPC style MCP mock server for embeddings.

## Start

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\mcp-servers\embedding-mcp
python server.py
```

Default port: `7001`.

Config fields:

- `PORT`: HTTP port, default `7001`
- `EMBEDDING_MOCK_MODE`: default `true`
- `EMBEDDING_DIMENSION`: default `8`
- `REAL_EMBEDDING_ENDPOINT`: reserved for future real embedding service

## Tools

### embed_text

Request:

```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "tools/call",
  "params": {
    "name": "embed_text",
    "arguments": {"text": "agent workflow"}
  }
}
```

Response:

```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "result": {
    "tool": "embed_text",
    "output": {
      "embedding": [0.196078, 0.533333],
      "dim": 8,
      "model": "mock-hash-embedding-v1",
      "mock": true
    }
  }
}
```

### embed_batch

Request arguments:

```json
{"texts": ["agent workflow", "knowledge memory"]}
```

Response output:

```json
{"items": [{"index": 0, "embedding": [0.196078]}], "dim": 8}
```
