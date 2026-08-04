# 生产记忆 Provider 实施计划

> 原文镜像：`docs/superpowers/plans/2026-06-06-production-memory-providers.md`

> **给 agentic workers：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施本计划。步骤使用 checkbox（`- [ ]`）语法追踪。

**目标：** 增加生产可用的 OpenAI embedding、Milvus vector-store 和 Neo4j interest-graph adapters，同时保留契约兼容的 memory modes。

**架构：** 每个 MCP `server.py` 保持为薄组合层和分发层。共享 lifecycle 与 health 行为放在 `mcp-servers/common`，聚焦的 memory/production adapter module 放在各 server 旁边。把 SDK client 注入 adapter，使单元测试能在没有网络服务的情况下验证生产行为。

**技术栈：** Python 3.12、官方 MCP Python SDK、OpenAI Python SDK v2、PyMilvus、Neo4j Python Driver v6、`unittest`、Docker Compose。

---

### Task 1：通用 Provider Lifecycle 与 Health

**文件：**

- 修改：`mcp-servers/common/simple_http_mcp.py`
- 新建：`mcp-servers/common/provider.py`
- 新建：`mcp-servers/tests/test_provider_lifecycle.py`

- [ ] 添加失败测试，证明初始化失败会被捕获、不健康 adapter 会拒绝调用、memory adapter 报告 healthy、`close()` 会被调用。
- [ ] 在 `mcp-servers` 目录运行 `python -m unittest tests.test_provider_lifecycle -v`；预期失败，因为 lifecycle helper 尚不存在。
- [ ] 实现 `ProviderState`、`ManagedProvider`，以及 `create_server` / `run_server` 可接受的动态 health callback。
- [ ] 重新运行 `python -m unittest tests.test_provider_lifecycle -v`；预期全部通过。

### Task 2：Embedding Providers

**文件：**

- 新建：`mcp-servers/embedding-mcp/providers.py`
- 替换：`mcp-servers/embedding-mcp/server.py`
- 新建：`mcp-servers/tests/test_embedding_provider.py`
- 修改：`mcp-servers/requirements.txt`

- [ ] 为确定性 memory embeddings、batching、有界 TTL cache、长文本分块、加权归一化合并、OpenAI retry、token/cost metrics、缺 key health 和维度不匹配添加失败测试。
- [ ] 运行 `python -m unittest tests.test_embedding_provider -v`；预期 import 或行为失败。
- [ ] 实现 `MemoryEmbeddingProvider`、`OpenAIEmbeddingProvider`、文本归一化/分块、cache、usage metrics 和 provider factory。
- [ ] 用 provider 调用替换 embedding MCP 分发，同时保留 `embed_text` 和 `embed_batch` 消费字段。
- [ ] 重新运行 embedding provider 和 MCP HTTP 测试；预期通过。

### Task 3：Milvus Vector Stores

**文件：**

- 新建：`mcp-servers/milvus-mcp/stores.py`
- 替换：`mcp-servers/milvus-mcp/server.py`
- 新建：`mcp-servers/tests/test_milvus_store.py`
- 修改：`mcp-servers/requirements.txt`

- [ ] 为稳定 ID、精确维度校验、memory CRUD、结构化 filter operators、不安全 delete 拒绝、vector deduplication、Milvus collection 创建和非破坏性 schema mismatch 处理添加失败测试。
- [ ] 运行 `python -m unittest tests.test_milvus_store -v`；预期 import 或行为失败。
- [ ] 实现共享 normalization/filter utilities、`MemoryVectorStore` 和 injected-client `MilvusVectorStore`。
- [ ] 暴露兼容既有 tools，并新增 `batch_insert_memory_vectors` 和 `delete_memory_vectors`。
- [ ] 重新运行 Milvus store 和 MCP HTTP 测试；预期通过。

### Task 4：Neo4j Interest Graph Stores

**文件：**

- 新建：`mcp-servers/neo4j-mcp/stores.py`
- 替换：`mcp-servers/neo4j-mcp/server.py`
- 新建：`mcp-servers/tests/test_neo4j_store.py`
- 修改：`mcp-servers/requirements.txt`

- [ ] 为稳定 event IDs、memory update 幂等性、固定参数化 Cypher、constraint/index 初始化、排序查询结果和推荐解释添加失败测试。
- [ ] 运行 `python -m unittest tests.test_neo4j_store -v`；预期 import 或行为失败。
- [ ] 实现 normalized update events、`MemoryInterestGraphStore` 和 injected-driver `Neo4jInterestGraphStore`。
- [ ] 替换 Neo4j MCP 分发，同时保留 aliases 和既有响应字段。
- [ ] 重新运行 Neo4j store 和 MCP HTTP 测试；预期通过。

### Task 5：Python Agent Client 契约

**文件：**

- 修改：`python-agent/app/mcp/base_client.py`
- 修改：`python-agent/app/mcp/milvus_client.py`
- 修改：`python-agent/app/mcp/neo4j_client.py`
- 修改：`python-agent/app/mcp/policy.py`
- 修改：`python-agent/tests/test_mcp_client.py`
- 修改：`python-agent/tests/test_mcp_policy.py`

- [ ] 为 batch insert、delete、metadata-filter search、memory fallback schemas 和稳定 Neo4j `event_id` forwarding 添加失败测试。
- [ ] 运行聚焦 Agent MCP 测试；预期缺少方法或 permission 失败。
- [ ] 扩展 memory tool schemas/behavior、client convenience methods 和 memory-only 写权限。
- [ ] 重新运行聚焦 Agent MCP 测试；预期通过。

### Task 6：Production Compose、初始化和集成测试

**文件：**

- 修改：`docker-compose.yml`
- 修改：`.env.example`
- 修改：`mcp-servers/Dockerfile`
- 新建：`scripts/init_memory_services.py`
- 新建：`scripts/integration_memory_services.py`
- 修改：`scripts/integration_test.ps1`
- 修改：`README.md`
- 修改：`mcp-servers/README.md`
- 修改：`mcp-servers/embedding-mcp/README.md`
- 修改：`mcp-servers/milvus-mcp/README.md`
- 修改：`mcp-servers/neo4j-mcp/README.md`

- [ ] 添加 `production` Compose profile，包含 etcd、MinIO、Milvus、Neo4j、持久卷、来自环境的凭据和 dependency health checks。
- [ ] 配置生产 MCP adapters，不在源码中嵌入 embedding secret。
- [ ] 添加幂等初始化脚本和 opt-in Docker-backed 集成脚本。
- [ ] 记录 memory startup、production startup、安全 Milvus migration 行为、health checks 和 opt-in OpenAI smoke testing。
- [ ] 运行 `docker compose config`；预期 Compose 输出有效。

### Task 7：验证与需求审计

**文件：**

- 仅修改验证过程中发现失败所需的文件。

- [ ] 在 `mcp-servers` 目录运行 `python -m unittest discover -s tests -v`。
- [ ] 在 `python-agent` 目录运行 `python -m unittest discover -s tests -v`。
- [ ] 运行 `python -m compileall mcp-servers python-agent`。
- [ ] 运行 `docker compose config`。
- [ ] Docker 依赖可用时运行 Docker-backed memory-service 集成测试；否则报告明确 blocker。
- [ ] 对照设计中的每条验收标准审计最终 diff，并确认没有回滚无关 dirty-worktree 改动。
