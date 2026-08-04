# 生产记忆 Provider 设计

> 原文镜像：`docs/superpowers/specs/2026-06-06-production-memory-providers-design.md`

日期：2026-06-06

## 目标

把当前只支持 Milvus、Neo4j 和 embedding mock 的 MCP server 实现，替换为生产可用的 adapters，同时保留确定性的进程内实现，用于本地开发和自动化测试。

实现必须保留现有 MCP 边界。Python Agent 代码继续通过统一 MCP client 调用 MCP tools，永远不 import 或直接调用 MCP server 内部实现。

## 已确认决策

- 使用 provider/repository interfaces，并分别提供 memory 与 production 实现。
- 使用 OpenAI-compatible Embeddings API，并以 `text-embedding-3-large` 作为默认真实 embedding 模型。
- GPT-5.5 继续用于 Agent generation/reasoning 调用，不用于 embedding generation。
- 默认 embedding dimension 使用 `3072`，并通过环境变量配置。
- Milvus collection 命名为 `user_memory_vectors`。
- 如果已有 Milvus collection 的 schema 或 vector dimension 不兼容，不自动 drop、recreate 或 mutate。服务标记 unhealthy，并拒绝受影响操作，直到管理员显式迁移或选择新的 collection。
- 生产依赖不可用时 MCP 进程保持存活。Health check 报告依赖错误，MCP tool call 返回结构化失败，使 Agent 既有 retry、circuit breaker 和 memory fallback 能安全降级。
- 永远不在仓库中保存 API keys 或 database passwords。

## 备选方案

### Provider 与 Repository 层

每个 MCP server 暴露当前 tool 边界，并把工作委托给一个小接口；该接口由 memory adapter 和 production adapter 共同实现。

这是最终选择，因为它让 memory 与 production modes 共享同一行为契约，使失败行为可以独立测试，并把数据库 SDK 细节隔离在 MCP 请求分发之外。

### 在现有 Server 文件中加入 Production 分支

直接在每个 `server.py` 中添加 `if mock_mode` 分支会少改一些文件，但会把 MCP schemas、lifecycle、cache、retry、database queries 和业务规则混在一起。该方案被拒绝，因为模块会难以测试和维护。

### 独立内部微服务

把数据库 adapters 放到额外网络服务后面可以提供强隔离，但会给当前项目增加不必要的部署面和失败面。该方案超出当前范围。

## 架构

每个 MCP server 保持薄组合层和 tool dispatch 层：

```text
Official MCP Server
  -> tool input validation
  -> provider/repository interface
  -> memory adapter or production adapter
  -> normalized result
  -> tool output validation
```

三个服务使用以下接口：

- `EmbeddingProvider`
  - `embed_text(text, options)`
  - `embed_batch(texts, options)`
  - `health()`
  - `close()`
- `VectorStore`
  - `initialize()`
  - `upsert(item)`
  - `upsert_batch(items)`
  - `search(vector, limit, metadata_filter)`
  - `delete(ids, metadata_filter)`
  - `deduplicate(items, threshold, metadata_filter)`
  - `health()`
  - `close()`
- `InterestGraphStore`
  - `initialize()`
  - `query_user_interests(user_id, limit)`
  - `update_user_interests(event)`
  - `get_related_topics(topic, limit)`
  - `explain_recommendation(user_id, article)`
  - `health()`
  - `close()`

Production SDK clients 每个 MCP 进程创建一次，并在 server shutdown 时关闭。Neo4j driver 生命周期覆盖整个进程，并且线程安全。Milvus 和 OpenAI clients 也会复用，而不是每次 tool call 重新创建。

## Embedding Provider

### 配置

- `EMBEDDING_PROVIDER`：`memory` 或 `openai`
- `EMBEDDING_MODEL`：默认 `text-embedding-3-large`
- `EMBEDDING_DIMENSION`：真实模式默认 `3072`，memory 模式可配置
- `OPENAI_BASE_URL`：默认 `https://api.openai.com/v1`
- `OPENAI_API_KEY`：仅真实 OpenAI 模式必需
- `EMBEDDING_TIMEOUT_SECONDS`
- `EMBEDDING_MAX_RETRIES`
- `EMBEDDING_BATCH_SIZE`
- `EMBEDDING_MAX_CHARS_PER_CHUNK`
- `EMBEDDING_MAX_CHUNKS`
- `EMBEDDING_CACHE_SIZE`
- `EMBEDDING_CACHE_TTL_SECONDS`
- `EMBEDDING_COST_PER_MILLION_TOKENS_USD`：可选

Provider 不得在 health responses、logs、MCP results 或 exceptions 中暴露 `OPENAI_API_KEY`。

### 文本处理

输入文本在 hashing 和 caching 前归一化。空文本会被拒绝。超过配置安全 chunk size 的文本，会尽量按段落或句子边界切分；必要时按硬字符边界回退。总 chunk 数受上限控制。

每个 chunk 通过 batched API request 生成 embedding。多 chunk embeddings 使用 token-weighted average 合并，然后做 L2 normalization。Provider 校验每个返回向量都符合配置维度。

Cache key 包含 provider name、base URL identity、model、dimension 和 normalized text hash。缓存值包含 vector 和 usage metadata。初始 cache 为进程本地有界 TTL/LRU cache；分布式 cache 不在本范围内。

### Usage 与 Cost

Embedding 结果包含：

- `embedding`
- `dim`
- `model`
- `provider`
- `mock`
- `cache_hit`
- `token_count`
- `latency_ms`
- `estimated_cost_usd`
- `truncated`
- `chunk_count`

Token usage 优先取 provider response。只有配置 `EMBEDDING_COST_PER_MILLION_TOKENS_USD` 时才计算成本，否则为 `null`，避免硬编码可能过期的价格。

日志记录 text hash 和长度，不记录完整长文本。敏感 metadata keys 使用现有 MCP log redaction rules。

## Milvus Vector Store

### Collection Schema

Production adapter 创建并校验 `user_memory_vectors`，字段包括：

- `id`：`VARCHAR`，primary key，应用侧生成的稳定 ID
- `embedding`：`FLOAT_VECTOR`，配置维度
- `user_id`：`VARCHAR`
- `source`：`VARCHAR`
- `topic`：`VARCHAR`
- `external_id`：`VARCHAR`
- `content_hash`：`VARCHAR`
- `created_at`：integer Unix timestamp
- `metadata_json`：JSON

Vector index 使用 `HNSW` 和 `COSINE`。Index 构建与 search 参数可配置，并提供生产导向默认值。

启动时 adapter：

1. 连接 Milvus。
2. Collection 和 index 缺失时创建。
3. 校验每个必需字段、primary-key 类型、vector 类型、dimension，以及已有 metric。
4. Load collection。
5. 为 `/health` 记录初始化状态。

任何不兼容 schema 都会让服务 unhealthy。Adapter 不会自动删除或重建生产数据。

### 稳定 ID 与写入

调用方可以提供显式 ID。如果省略，server 生成：

```text
sha256(user_id + "\0" + source + "\0" + (external_id or content_hash))
```

未显式提供 `content_hash` 时，会从归一化源内容派生。Store 使用 upsert，使重试和同一逻辑记录重放会更新同一 primary key，而不是创建重复项。

所有 insert 都会校验 vector length 与配置 dimension 精确匹配。Dimension mismatch 是结构化 validation error，绝不会被静默截断、padding 或投影。

### Metadata Filters

MCP 调用方传入结构化 filter object，不能传原始 Milvus filter expressions。支持字段必须显式 allowlist。初始 operators：

- `eq`
- `in`
- `gte`
- `lte`

Adapter 在编译 filter expression 前校验字段名、操作符、值和 list size。字符串值由 compiler 安全 escape。无效 filter 在任何数据库调用前被拒绝。

### Search、Delete 与 Deduplication

- Search 接受 vector、limit、可选 minimum score 和结构化 metadata filter。
- Delete 接受显式稳定 IDs 或结构化 metadata filter。空的无条件 delete 会被拒绝。
- Batch insert 在写入前校验每个 item。无效 batch 不会部分写入。
- Semantic deduplication 比较输入 batch 内的 vectors，并可在相同 metadata scope 下搜索既有 collection 记录。达到或超过阈值的 item 返回 canonical ID，且不会再次插入。

Memory mode 实现相同的精确维度检查、稳定 ID 生成、filter 语义、CRUD 行为和基于 vector 的 deduplication。

## Neo4j Interest Graph

### Graph Model

```text
(:User {id})
  -[:INTERESTED_IN {weight, updated_at, last_event_id}]->
(:Topic {name})

(:Topic)-[:RELATED_TO {weight}]->(:Topic)

(:InterestEvent {id, user_id, created_at})
```

初始化时幂等创建 constraints 和 indexes：

- `User.id` 唯一约束
- `Topic.name` 唯一约束
- `InterestEvent.id` 唯一约束
- 固定查询模式所需 indexes

### 参数化 Cypher

每个查询都是代码中的固定 Cypher statement。值只通过 Neo4j driver parameters 提供。用户输入永远不会拼接进 Cypher identifiers、labels、relationship types、predicates 或 values。

Adapter 使用一个进程生命周期内的 driver；启动时验证 connectivity；read 使用 read routing；write 在 managed transactions 中执行；shutdown 时关闭 driver。

### 幂等兴趣更新

每次更新携带稳定 `event_id`。如果调用方未提供，server 会从 user ID 和 normalized update payload 派生。

写事务首先 merge `InterestEvent {id: $event_id}`。只有 event 新创建时，才更新关系 weight 和 timestamp。因此重放同一 event 会返回 success，但不会再次应用 weight 变化。

显式 topic weights、snapshot interests 和 extracted feedback 在进入 memory 或 Neo4j adapter 前归一化为同一 event model。Weight 值保持在闭区间 `0..1`。

### 查询与推荐解释

用户兴趣查询返回带权重的 ranked topics。相关主题查询遍历固定 `RELATED_TO` paths，并限制 depth 和结果数量。

推荐解释接受结构化 article fields 和 topic names。它返回：

- 直接匹配到的用户 topics
- 对结果有贡献的 related-topic paths
- 关系权重和兴趣权重
- 归一化分数
- 由返回图数据派生的人类可读 reason strings

解释结果是确定性的，不需要 LLM 调用。

## MCP Tool Contract 变更

为保持兼容，既有 tool names 保留：

- `embed_text`
- `embed_batch`
- `insert_memory_vector`
- `search_similar_memory`
- `search_related_articles`
- `search_articles`
- `semantic_deduplicate`
- `query_user_interest_graph`
- `update_user_interest_graph`
- `get_related_topics`
- `explain_recommendation`

Milvus 新增：

- `batch_insert_memory_vectors`
- `delete_memory_vectors`

既有 tools 增加可选结构化字段，例如 `user_id`、`metadata_filter`、`minimum_score` 和 `event_id`。Output schemas 增加 provider 和 operation metadata，同时保留当前已消费字段。

Python Agent 的 `MilvusClient` 增加 batch insert、delete 和 structured-filter searches 的 convenience methods。Agent permission policy 只把新的写 tools 授权给 `memory` Agent。所有调用仍通过 `BaseMcpClient` 做权限检查、schema validation、logging、timeout、retry、circuit breaking 和 fallback。

## Lifecycle 与 Health

每个 server 在接受有效生产调用前初始化 adapter。初始化错误会作为 dependency state 捕获，而不是终止进程。

`GET /health` 在配置的生产依赖不可用或不兼容时返回非成功 HTTP status，body 包含：

- MCP server name
- operating mode
- dependency status
- 不含凭据的 provider/database identity
- 适用时的 configured model、collection 和 vector dimension
- 最近一次 initialization 或 health error

Memory mode 不需要外部服务即可报告 healthy。

生产 adapter 不可用时发起的 tool call 会返回结构化 MCP tool error。Python Agent 通过既有 resilience layer 处理，并可在 `MCP_MEMORY_FALLBACK=true` 时回退到进程内 memory MCP 实现。

## Docker 与初始化

开发保持轻量：

```text
docker compose up
```

除非显式覆盖，否则使用 memory MCP provider modes。

`production` Compose profile 新增：

- Milvus standalone
- etcd
- MinIO
- Neo4j
- production-mode embedding、Milvus 和 Neo4j MCP servers

为 Milvus、MinIO、etcd 和 Neo4j 声明 persistent volumes。服务使用依赖级 health checks。MCP production services 依赖 healthy database services，但仍保留自己的 health reporting。

初始化脚本只负责安全、幂等设置：

- Milvus collection 创建与 schema validation
- Neo4j constraints、indexes 和可选 seed topic relationships

任何初始化脚本都不 drop 或 recreate 现有生产数据。

OpenAI API key 通过 `OPENAI_API_KEY` 或 Docker secret 提供，不写入 Compose defaults 或 committed files。

## 失败处理

- 真实模式缺少 OpenAI key：embedding MCP 保持存活，报告 unhealthy，并返回结构化 tool errors。
- OpenAI timeout 或 transient error：先应用 provider-level 有界 retry，然后返回 MCP tool error。Agent 可执行自己的有界 retry 和 fallback。
- Embedding dimension mismatch：立即拒绝 response 或 write。
- Milvus 不可用：服务保持存活并报告 unhealthy；tools fail，但不 crash Agent task。
- Milvus collection schema mismatch：服务保持存活，报告精确 mismatch，并拒绝操作，不做 mutation。
- Neo4j 不可用：服务保持存活并报告 unhealthy；tools fail，但不 crash Agent task。
- 无效 metadata filter 或 unsafe delete：在调用 Milvus 前拒绝。
- 重复 Neo4j event：返回 success，并设置 `applied=false`。

## 测试策略

### Unit Tests

Embedding tests 覆盖：

- deterministic memory vectors
- real provider batching
- cache hits 和 cache-key isolation
- timeout 和 retry behavior
- usage 和 configurable cost calculation
- safe chunking 和 combined-vector normalization
- provider dimension mismatch
- missing-key unhealthy behavior

Milvus tests 覆盖：

- collection creation 和 validation
- incompatible dimension rejection 且没有 destructive calls
- stable ID generation
- single 和 batch upsert
- exact dimension validation
- structured metadata filter compilation 和 invalid-filter rejection
- search 和 delete
- unsafe empty delete rejection
- batch 和 collection semantic deduplication

Neo4j tests 覆盖：

- idempotent constraint 和 index initialization
- parameterized query execution
- repeated event updates applying once
- ranked interest queries
- related-topic queries
- recommendation explanation
- driver lifecycle 和 unavailable dependency behavior

Production adapters 注入 SDK clients，使单元测试可以用 fakes 验证调用和参数，不需要网络服务。

### Integration Tests

Docker-backed integration tests 连接真实 Milvus 和 Neo4j 服务，并验证：

- Milvus collection schema、CRUD、metadata filtering、stable upsert 和 semantic deduplication
- Neo4j constraints、parameterized workflows、idempotent updates、queries 和 explanations
- MCP `tools/list` 和 `tools/call` over Streamable HTTP
- dependencies healthy 和 unavailable 时的 health behavior
- Agent permission denial、timeout、retry、circuit breaker 和 memory fallback

真实 OpenAI 网络测试是 opt-in，只有显式 smoke test flag 和 `OPENAI_API_KEY` 都存在时才运行。普通 CI 使用 fake OpenAI client 验证 embedding contract，避免成本和网络依赖。

### Regression Verification

既有 Python Agent、MCP server、Go backend、protobuf contract 和 smoke test suites 仍属于最终验证。测试命令和生产启动说明记录在根 README。

## 验收标准

- Memory mode 在没有 Milvus、Neo4j 或 OpenAI key 时可用。
- Real embedding mode 支持 single/batch 调用、cache、timeout、retry、usage metrics、configurable cost 和安全长文本处理。
- `user_memory_vectors` 被安全创建和校验。
- Milvus 支持稳定 single/batch upsert、search、structured metadata filters、delete 和基于 vector 的 semantic deduplication。
- 不静默接受或破坏性迁移任何 vector dimension mismatch。
- Neo4j constraints 和 indexes 幂等创建。
- 没有 Cypher query 拼接用户提供的值。
- 重放同一 interest event 不会让 relationship weights 变化两次。
- Recommendation explanations 包含 graph-derived reasons。
- Production dependency failures 不会 crash MCP process 或 Agent task。
- Docker production profile、initialization scripts、health checks、integration tests 和 README instructions 存在且已验证。
