# embedding-mcp 中文说明

> 原文镜像：`mcp-servers/embedding-mcp/README.md`

Tools：

- `embed_text`
- `embed_batch`

`EMBEDDING_PROVIDER=memory` 返回确定性的本地向量。`EMBEDDING_PROVIDER=openai` 使用兼容 OpenAI 的 Embeddings API，并默认使用 `text-embedding-3-large`。

真实模式支持有界 batch、TTL/LRU cache、timeout、retry、安全长文本分块、归一化 chunk 合并、维度校验、token usage、latency，以及通过 `EMBEDDING_COST_PER_MILLION_TOKENS_USD` 可选计算成本。

使用 `OPENAI_API_KEY` 或 `OPENAI_API_KEY_FILE` 提供凭据；凭据不会出现在 health 输出或 MCP 结果中。
