# MCP Servers

These standalone services use the official MCP Python SDK and support `stdio`
and Streamable HTTP `/mcp` transports.

## Install

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\mcp-servers
pip install -r requirements.txt
```

## Memory Mode

Memory mode requires no OpenAI, Milvus, or Neo4j service:

```powershell
$env:MCP_TRANSPORT="streamable_http"
$env:EMBEDDING_PROVIDER="memory"
python .\embedding-mcp\server.py
```

Equivalent provider values are `MILVUS_PROVIDER=memory` and
`NEO4J_PROVIDER=memory`. Legacy `*_MOCK_MODE=true` remains supported.

## Production Mode

- Embedding: `EMBEDDING_PROVIDER=openai`
- Milvus: `MILVUS_PROVIDER=milvus`
- Neo4j: `NEO4J_PROVIDER=neo4j`

Use `text-embedding-3-large` with `EMBEDDING_DIMENSION=3072` unless an explicit
dimension migration has been planned. The Milvus adapter creates and validates
`user_memory_vectors`; it never drops an incompatible collection.

Credentials come from environment variables or mounted secret files:

- `OPENAI_API_KEY` or `OPENAI_API_KEY_FILE`
- `MILVUS_TOKEN` or `MILVUS_TOKEN_FILE`
- `NEO4J_PASSWORD` or `NEO4J_PASSWORD_FILE`

Every HTTP server exposes `/health`. Production dependency failures return
HTTP `503` but do not terminate the MCP process.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Docker-backed tests are skipped unless
`RUN_MEMORY_SERVICES_INTEGRATION=1`. The paid OpenAI smoke test additionally
requires `RUN_OPENAI_EMBEDDING_SMOKE=1` and `OPENAI_API_KEY`.
