# embedding-mcp

Tools:

- `embed_text`
- `embed_batch`

`EMBEDDING_PROVIDER=memory` returns deterministic local vectors.
`EMBEDDING_PROVIDER=openai` uses the OpenAI-compatible Embeddings API with
`text-embedding-3-large` by default.

Real mode supports bounded batches, TTL/LRU cache, timeout, retry, safe
long-text chunking, normalized chunk merging, dimension validation, token
usage, latency, and optional cost calculation through
`EMBEDDING_COST_PER_MILLION_TOKENS_USD`.

Use `OPENAI_API_KEY` or `OPENAI_API_KEY_FILE`; credentials are never included
in health output or MCP results.
