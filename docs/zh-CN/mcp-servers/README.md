# MCP Servers 中文说明

> 原文镜像：`mcp-servers/README.md`

这些独立服务使用官方 MCP Python SDK，并支持 `stdio` 和 Streamable HTTP `/mcp` 两种 transport。

## 安装

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\mcp-servers
pip install -r requirements.txt
```

## Memory Mode

Memory mode 不需要 OpenAI、Milvus 或 Neo4j 服务：

```powershell
$env:MCP_TRANSPORT="streamable_http"
$env:EMBEDDING_PROVIDER="memory"
python .\embedding-mcp\server.py
```

等价 provider 值包括 `MILVUS_PROVIDER=memory` 和 `NEO4J_PROVIDER=memory`。旧版 `*_MOCK_MODE=true` 仍受支持。

## Production Mode

- Embedding：`EMBEDDING_PROVIDER=openai`
- Milvus：`MILVUS_PROVIDER=milvus`
- Neo4j：`NEO4J_PROVIDER=neo4j`

除非已经规划显式维度迁移，否则使用 `text-embedding-3-large` 和 `EMBEDDING_DIMENSION=3072`。Milvus adapter 会创建并校验 `user_memory_vectors`；它不会 drop 不兼容的 collection。

凭据来自环境变量或挂载的 secret 文件：

- `OPENAI_API_KEY` 或 `OPENAI_API_KEY_FILE`
- `MILVUS_TOKEN` 或 `MILVUS_TOKEN_FILE`
- `NEO4J_PASSWORD` 或 `NEO4J_PASSWORD_FILE`

每个 HTTP server 都暴露 `/health`。生产依赖失败时返回 HTTP `503`，但不会终止 MCP 进程。

## Fetch SSRF 防护

`fetch-mcp` 只接受绝对 `http` 和 `https` URL。它会拒绝 userinfo、localhost、私网、链路本地地址、`169.254.169.254` 和 `metadata.google.internal` 等云元数据主机，以及 DNS 解析后落到受限地址的域名。Redirect 会被阻断，响应体由 `FETCH_MAX_RESPONSE_BYTES` 限制。

文件和邮件类 MCP tools 在 Python Agent policy 中属于高风险能力，默认禁用。启用前先阅读 `SECURITY.md`。

## 测试

```powershell
python -m unittest discover -s tests -v
```

Docker-backed 测试会跳过，除非设置 `RUN_MEMORY_SERVICES_INTEGRATION=1`。付费 OpenAI smoke test 还需要 `RUN_OPENAI_EMBEDDING_SMOKE=1` 和 `OPENAI_API_KEY`。
