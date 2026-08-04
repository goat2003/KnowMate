# Feedback Agent、Memory Agent 与用户画像版本化设计

> 原文镜像：`docs/superpowers/specs/2026-06-08-feedback-memory-profile-versioning-design.md`
>
> 原文件已以中文为主；本镜像保留命令、路径、代码块和协议字段原样。


日期：2026-06-08

## 目标

完善用户反馈到长期记忆的闭环，使 Feedback Agent、Memory Agent、MySQL、Milvus 和 Neo4j 之间的更新过程具备一致性、可追踪性和可回滚能力。

本设计覆盖：

- 用户反馈处理幂等性
- 原始反馈与结构化反馈保存
- 用户画像每次更新生成新版本
- 用户画像版本历史查询
- 用户画像回滚到历史版本
- 兴趣权重范围限制
- 短期反馈对长期兴趣的渐进式影响
- 正反馈、负反馈和风格偏好的差异化更新策略
- Milvus、Neo4j、MySQL 部分失败时的重试与补偿
- 画像更新前后差异记录
- 查看用户画像 API
- 查看画像版本历史 API
- 回滚画像 API
- 查看推荐解释 API
- 重新构建用户画像任务
- 并发反馈、重复反馈和部分失败测试

## 已确认决策

- 采用“GoFrame 持久化与审计，Python Agent 负责信号抽取与画像合并策略”的方案。
- GoFrame 负责原始反馈、结构化反馈、画像版本、画像差异、回滚记录和补偿任务的 MySQL 持久化。
- Python `FeedbackAgent` 负责把反馈抽取为正反馈、负反馈和风格偏好三类结构化信号。
- Python `MemoryAgent` 负责在当前画像副本上执行受限的权重合并策略，并返回新画像、结构化反馈、画像差异和 MCP 调用日志。
- Milvus 和 Neo4j 失败不直接丢弃反馈，也不让已经成功的 MySQL 原始反馈记录消失；失败项进入补偿任务。
- 回滚不删除历史版本，而是基于历史版本生成新的 active 版本，保留完整审计链路。
- 推荐解释 API 优先复用已有 `score_breakdown`、`recommendation_reasons`、`rejection_reasons`、画像版本和 MCP 日志，不引入新的 LLM 依赖。

## 现状与问题

当前反馈链路为：

```text
POST /feedback
  -> harness.ProcessFeedback
     -> feedback_logs 保存原始反馈
     -> LatestUserProfileSnapshot 读取当前画像
     -> Python Agent ProcessFeedback
        -> FeedbackAgent 提取 sentiment 和 extracted_feedback
        -> MemoryAgent 更新 user_profile_snapshot
        -> 可选调用 embedding / Milvus / Neo4j
     -> user_profile_snapshot 插入新快照
     -> mcp_call_logs 写入 MCP 日志
```

现有能力已经具备基本反馈闭环，但存在以下问题：

- `feedback_logs` 只有按 `run_id` 的唯一约束，不能表达业务幂等键。
- 原始反馈保存了文本和元数据，但结构化反馈没有独立持久化字段。
- `user_profile_snapshot` 每次插入一条记录，但没有显式版本号、active 指针、base version、回滚来源和差异。
- `LatestUserProfileSnapshot` 只能读取最新插入记录，不能区分正常更新和回滚生成的新版本。
- `MemoryAgent` 只更新 `last_feedback_sentiment`、`feedback_count` 和 `latest_feedback`，没有长期兴趣权重策略。
- 兴趣权重没有统一范围约束，短期反馈可能在未来实现中错误地覆盖长期兴趣。
- 正反馈、负反馈和风格偏好没有分层处理。
- Milvus 和 Neo4j 调用结果只体现在 MCP 日志中，没有可重试的补偿任务。
- MySQL 写入画像失败时，原始反馈虽然已经保存，但没有清晰的待重试状态。
- 推荐排序已经返回解释字段，但 GoFrame 缺少面向 API 的推荐解释查询能力。

## 方案对比

### 方案一：GoFrame 负责持久化审计，Python Agent 负责策略合并

GoFrame 保持 HTTP API、MySQL 事务、画像版本、回滚和补偿任务的所有权；Python Agent 保持偏好理解、画像权重合并和 MCP 工具调用的所有权。

优点：

- 符合现有代码边界，HTTP 和 MySQL 已集中在 GoFrame。
- Python Agent 的职责保持在智能处理与工具调用，不承担业务审计表查询。
- 回滚、历史、补偿任务可以用 MySQL 保证可追踪。
- 单元测试可以在 Go 和 Python 两侧分别覆盖。

这是选定方案。

### 方案二：全部放在 Python Agent

Python Agent 同时负责反馈抽取、画像版本、补偿任务和历史查询。短期文件改动可能更集中，但 GoFrame API 需要绕过现有 store/harness 边界，且 MySQL 审计链路会分散，因此不采用。

### 方案三：新增独立 Memory Service

新增服务统一管理画像、记忆和补偿。边界清晰，但当前项目仍处于本地可验证的 MVP 阶段，引入新服务会增加部署、配置和测试成本，因此不纳入本轮。

## 总体架构

```text
POST /feedback
  -> 计算 feedback_idempotency_key
  -> MySQL 事务保存/读取 feedback_logs
  -> 若已处理成功，直接返回既有结果
  -> 读取 active user_profile_snapshot
  -> 调用 Python ProcessFeedback
     -> FeedbackAgent 生成 structured_feedback
     -> MemoryAgent 生成 updated_profile_snapshot + profile_diff
     -> MemoryAgent 调用 embedding / Milvus / Neo4j
  -> MySQL 事务插入新画像版本
  -> 更新 feedback_logs structured_feedback/status/profile_version
  -> 写 mcp_call_logs
  -> 对失败的 MySQL/Milvus/Neo4j 项生成 compensation task
```

画像查询链路：

```text
GET /profile
  -> 读取 user_profile_snapshot is_active = true

GET /profile/history
  -> 按 version desc 读取 user_profile_snapshot

POST /profile/rollback
  -> 读取目标历史版本
  -> 插入 version = latest + 1 的新 active 版本
  -> diff_json 记录 rollback 前后变化
  -> 旧 active 置为 false
```

画像重建链路：

```text
POST /profile/rebuild
  -> 创建 profile_rebuild run_log 或 compensation task
  -> 读取该用户已处理的 structured_feedback
  -> 从默认画像或指定 base version 重放 MemoryAgent 合并策略
  -> 插入新的 active snapshot
  -> 记录 rebuild diff 和来源反馈范围
```

推荐解释链路：

```text
GET /recommendations/explain?post_id=...
  -> posts 定位 article_uid
  -> run_logs/mcp_call_logs/可选 posts metadata 定位推荐信息
  -> 返回 score_breakdown、recommendation_reasons、rejection_reasons、profile_version、相关 MCP 日志摘要
```

## 数据模型设计

### feedback_logs 扩展

保留现有字段，并新增：

- `idempotency_key VARCHAR(128) NOT NULL DEFAULT ''`
- `raw_feedback_json JSON NULL`
- `structured_feedback_json JSON NULL`
- `process_status VARCHAR(32) NOT NULL DEFAULT 'received'`
- `profile_version INT NULL`
- `error_message TEXT NULL`
- `processed_at DATETIME NULL`

约束与索引：

- `UNIQUE KEY uk_feedback_idempotency (user_id, idempotency_key)`
- `KEY idx_feedback_status_created (process_status, created_at)`
- `KEY idx_feedback_user_profile_version (user_id, profile_version)`

幂等键生成规则：

- 如果请求带 `idempotency_key`，优先使用请求值。
- 如果未带，则由 `user_id + post_id + article_id + feedback_type + rating + normalized_feedback_text` 生成 SHA-256。
- 同一个幂等键重复请求时：
  - 如果已有 `completed`，直接返回已有结构化反馈和画像版本。
  - 如果已有 `processing`，返回当前状态，不重复触发 Agent。
  - 如果已有 `failed` 或 `compensating`，允许进入重试路径，但不能重复创建原始反馈记录。

### user_profile_snapshot 扩展

保留现有字段，并新增：

- `version INT NOT NULL DEFAULT 1`
- `base_version INT NULL`
- `run_id VARCHAR(128) NOT NULL DEFAULT ''`
- `diff_json JSON NULL`
- `change_reason VARCHAR(128) NOT NULL DEFAULT ''`
- `source_feedback_id BIGINT UNSIGNED NULL`
- `is_active BOOLEAN NOT NULL DEFAULT FALSE`
- `rolled_back_from_version INT NULL`

约束与索引：

- `UNIQUE KEY uk_profile_user_version (user_id, version)`
- `KEY idx_profile_user_active (user_id, is_active)`
- `KEY idx_profile_run_id (run_id)`

active 规则：

- 每个用户最多一条 `is_active = true`。
- 插入新版本时，在同一个 MySQL 事务中把旧 active 置为 false，再插入新 active。
- 若 MySQL 版本支持 partial unique index 不足，使用事务和行锁保证并发安全。

### memory_compensation_tasks 新表

字段：

- `id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY`
- `task_id VARCHAR(128) NOT NULL`
- `run_id VARCHAR(128) NOT NULL`
- `user_id VARCHAR(128) NOT NULL`
- `task_type VARCHAR(64) NOT NULL`
- `target_system VARCHAR(32) NOT NULL`
- `payload_json JSON NOT NULL`
- `status VARCHAR(32) NOT NULL DEFAULT 'pending'`
- `attempt_count INT NOT NULL DEFAULT 0`
- `max_attempts INT NOT NULL DEFAULT 5`
- `next_retry_at DATETIME NULL`
- `last_error TEXT NULL`
- `created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP`
- `updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP`

约束与索引：

- `UNIQUE KEY uk_memory_compensation_task_id (task_id)`
- `KEY idx_memory_compensation_status_retry (status, next_retry_at)`
- `KEY idx_memory_compensation_run (run_id)`
- `KEY idx_memory_compensation_user (user_id)`

任务类型：

- `profile_snapshot_insert`
- `milvus_memory_vector_insert`
- `neo4j_interest_graph_update`
- `mcp_log_insert`
- `profile_rebuild`

### 推荐解释数据

本轮优先不新增复杂表。推荐解释 API 从已有 `posts`、`run_logs`、`mcp_call_logs` 和 Agent 返回字段中组装。

如果现有 `posts` 没有保存 `score_breakdown` 等字段，则在实施中优先扩展 `posts.metadata JSON NULL` 或新增轻量 `recommendation_explanations` 表。选型原则：

- 若只需按 post 查询，扩展 `posts.metadata` 更轻。
- 若需要按 run/article 批量分析，新增 `recommendation_explanations` 更清晰。

本轮推荐新增 `posts.metadata JSON NULL`，保存：

- `rank_position`
- `score`
- `score_breakdown`
- `recommendation_reasons`
- `rejection_reasons`
- `profile_version`

## Python Agent 设计

### 结构化反馈格式

`FeedbackAgent` 输出新增 `structured_feedback`，保持 `sentiment` 和 `extracted_feedback` 兼容字段。

结构示例：

```json
{
  "positive": [
    {"topic": "工程实践", "weight_delta": 0.08, "evidence": "希望多保留工程实践细节"}
  ],
  "negative": [
    {"topic": "营销软文", "weight_delta": -0.10, "evidence": "不想看营销内容"}
  ],
  "style_preferences": [
    {"name": "保留实现细节", "value": "more_details", "confidence": 0.8}
  ],
  "raw_signals": [
    {"type": "positive", "text": "希望多保留工程实践细节"}
  ]
}
```

兼容策略：

- `extracted_feedback` 继续返回字符串列表，供旧调用方使用。
- `structured_feedback` 进入新的 gRPC 字段；如果暂不改 proto，也可先作为 `updated_profile_snapshot["last_structured_feedback"]` JSON 字符串返回，但最终应进入 proto。

### 画像结构

画像仍通过 `map<string,string>` 传输，但关键字段采用 JSON 字符串：

- `topics`: `{"AI":0.72,"工程实践":0.61}`
- `negative_topics`: `{"营销软文":0.7}`
- `style_preferences`: `{"detail_level":"high","tone":"practical"}`
- `feedback_count`: `"12"`
- `last_feedback_sentiment`: `"positive"`
- `latest_feedback`: `"..."`，仅保留短期展示，不作为长期权重唯一来源。

### 权重范围

所有兴趣、负向兴趣和风格置信度都限制在 `0.0..1.0`：

```text
clamped = min(1.0, max(0.0, value))
```

异常输入处理：

- 非数字权重按 `0.0` 处理。
- 空 topic 不写入。
- 单次反馈的绝对增量不超过 `0.12`。
- 单次批量反馈对同一 topic 的累计绝对增量不超过 `0.20`。

### 长短期合并策略

短期反馈不能立即完全覆盖长期兴趣。采用渐进式合并：

```text
new_weight = long_term_weight * retention + feedback_signal * learning_rate
```

默认参数：

- 正反馈 `retention = 0.92`，`learning_rate = 0.08`
- 负反馈 `retention = 0.90`，`learning_rate = 0.10`
- 风格偏好 `retention = 0.85`，`learning_rate = 0.15`

解释：

- 正反馈用于增强已有兴趣或新增兴趣，增幅保守。
- 负反馈优先写入 `negative_topics`，并小幅降低对应正向 topic。
- 风格偏好不直接改变 topic 兴趣权重，而是更新 `style_preferences`。

### 差异记录

`MemoryAgent` 返回 `profile_diff`：

```json
{
  "before": {
    "topics": {"AI": 0.7}
  },
  "after": {
    "topics": {"AI": 0.7, "工程实践": 0.08}
  },
  "changes": [
    {
      "path": "topics.工程实践",
      "before": null,
      "after": 0.08,
      "reason": "positive_feedback",
      "evidence": "希望多保留工程实践细节"
    }
  ]
}
```

GoFrame 将该对象写入 `user_profile_snapshot.diff_json`。

### MCP 失败与补偿信号

`MemoryAgent` 已经通过 MCP client 得到结构化日志。实施时需要把失败日志转换为补偿任务：

- `insert_memory_vector` 失败：生成 `milvus_memory_vector_insert`
- `update_user_interest_graph` 失败：生成 `neo4j_interest_graph_update`
- MCP 日志写 MySQL 失败：生成 `mcp_log_insert`

Python 不直接管理补偿队列，只返回足够的 `mcp_call_logs` 和可重放 payload。

## GoFrame 设计

### ProcessFeedback 幂等流程

`harness.ProcessFeedback` 调整为：

1. 生成或读取 `idempotency_key`。
2. 在 MySQL 中尝试创建 `feedback_logs`，状态为 `received`。
3. 如果唯一键冲突，读取现有记录：
   - `completed`：直接返回已有结果。
   - `processing`：返回处理中状态。
   - `failed` / `compensating`：按重试路径处理。
4. 将记录状态更新为 `processing`。
5. 读取 active profile。
6. 调用 Python Agent。
7. 在事务中：
   - 锁定该用户当前 active profile。
   - 计算 next version。
   - 插入新 active profile。
   - 旧 active 置为 false。
   - 更新 feedback_logs 的 structured feedback、profile_version、status。
8. 写入 MCP 日志。
9. 对失败 MCP 日志创建补偿任务。
10. 返回结果。

### 并发版本控制

并发反馈对同一用户画像更新时必须串行化版本号：

- `InsertUserProfileSnapshotVersion` 内部使用事务。
- 查询当前 active profile 时使用 `FOR UPDATE`。
- next version = locked latest version + 1。
- 提交后只有新版本 `is_active = true`。

### 回滚流程

`POST /profile/rollback` 请求：

```json
{
  "user_id": "default-user",
  "target_version": 3,
  "reason": "manual_rollback"
}
```

响应：

```json
{
  "ok": true,
  "profile": {
    "user_id": "default-user",
    "version": 8,
    "base_version": 7,
    "rolled_back_from_version": 3,
    "snapshot": {}
  }
}
```

回滚规则：

- 目标版本必须属于同一用户。
- 目标版本可以是非 active 历史版本。
- 回滚生成新版本，不修改或删除历史版本。
- `diff_json` 记录回滚前 active 和目标版本内容差异。

### 画像重建流程

`POST /profile/rebuild` 请求：

```json
{
  "user_id": "default-user",
  "from_version": 1,
  "dry_run": false
}
```

实现策略：

- 第一阶段可同步执行，读取该用户所有 `completed` 且有 `structured_feedback_json` 的反馈。
- 从默认画像或指定 base version 开始重放 MemoryAgent 合并策略。
- 生成 `change_reason = rebuild` 的新 active version。
- 若重建过程中 Milvus 或 Neo4j 同步失败，写入补偿任务。

后续如反馈量变大，可把该 API 改为只创建 `profile_rebuild` 补偿任务，由后台 worker 异步处理。

## API 设计

### 查看用户画像

```text
GET /profile?user_id=default-user
```

响应：

```json
{
  "ok": true,
  "profile": {
    "user_id": "default-user",
    "version": 7,
    "summary": "positive",
    "snapshot": {
      "topics": "{\"AI\":0.72}",
      "style_preferences": "{\"detail_level\":\"high\"}"
    },
    "diff": {},
    "created_at": "2026-06-08T10:00:00Z"
  }
}
```

### 查看画像版本历史

```text
GET /profile/history?user_id=default-user&limit=20
```

响应：

```json
{
  "ok": true,
  "items": [
    {
      "user_id": "default-user",
      "version": 7,
      "base_version": 6,
      "change_reason": "feedback",
      "is_active": true,
      "diff": {},
      "created_at": "2026-06-08T10:00:00Z"
    }
  ]
}
```

### 回滚画像

```text
POST /profile/rollback
```

请求和响应见回滚流程。

### 查看推荐解释

```text
GET /recommendations/explain?post_id=feedback-xxx-a1
```

响应：

```json
{
  "ok": true,
  "explanation": {
    "post_id": "feedback-xxx-a1",
    "article_id": "a1",
    "profile_version": 7,
    "score": 8.2,
    "rank_position": 1,
    "score_breakdown": [],
    "recommendation_reasons": [],
    "rejection_reasons": [],
    "mcp_logs": []
  }
}
```

### 重新构建用户画像任务

```text
POST /profile/rebuild
```

请求和响应见画像重建流程。

## 失败处理与补偿

### MySQL 失败

原始反馈写入失败：

- 直接返回 failed。
- 不调用 Python Agent。
- 因原始反馈没有持久化，调用方需要重试。

画像版本写入失败：

- `feedback_logs` 保持 `processing` 或更新为 `failed`。
- 创建 `profile_snapshot_insert` 补偿任务。如果连补偿任务也写入失败，在 run log 中记录失败。
- 返回 failed，避免调用方误以为画像已更新。

MCP 日志写入失败：

- 不影响画像更新结果。
- 创建 `mcp_log_insert` 补偿任务。

### Milvus 失败

`insert_memory_vector` 失败时：

- 画像 MySQL 版本仍可提交。
- MCP log 标记 failed。
- 创建 `milvus_memory_vector_insert` 补偿任务。
- API 响应 `ok` 可以为 true，但 `result.steps` 中包含 `compensating`。

### Neo4j 失败

`update_user_interest_graph` 失败时：

- 画像 MySQL 版本仍可提交。
- MCP log 标记 failed。
- 创建 `neo4j_interest_graph_update` 补偿任务。
- 查询画像 API 仍以 MySQL active profile 为准。

### 补偿重试

补偿任务采用指数退避：

```text
next_retry_at = now + min(2^attempt_count minutes, 60 minutes)
```

任务达到 `max_attempts` 后标记为 `dead_letter`，保留 `last_error` 供人工排查。

## 测试设计

### Python 测试

新增或扩展：

- `test_feedback_agent_extracts_structured_feedback`
- `test_memory_agent_clamps_interest_weights`
- `test_memory_agent_does_not_allow_short_term_feedback_to_override_long_term_interest`
- `test_memory_agent_applies_positive_negative_and_style_strategies_differently`
- `test_memory_agent_reports_profile_diff`
- `test_memory_agent_returns_failed_mcp_logs_for_compensation`
- `test_process_feedback_reuses_cached_response_for_concurrent_duplicate_request`

测试要求：

- 使用 mock LLM/MCP 或本地内存 transport。
- 不依赖公网。
- 不依赖真实 Milvus/Neo4j。

### Go 测试

新增或扩展：

- `TestProcessFeedbackIsIdempotentForDuplicateFeedback`
- `TestConcurrentFeedbackCreatesMonotonicProfileVersions`
- `TestProcessFeedbackPersistsRawAndStructuredFeedback`
- `TestProfileHistoryListsVersionsNewestFirst`
- `TestRollbackProfileCreatesNewActiveVersion`
- `TestRecommendationExplanationUsesPersistedMetadata`
- `TestFailedMilvusOrNeo4jLogCreatesCompensationTask`
- `TestProfileRebuildReplaysStructuredFeedback`

测试要求：

- store 层单元测试覆盖幂等键、版本号和 diff JSON。
- harness 测试使用 fake store / fake Agent response。
- 需要真实 MySQL 行锁语义的测试放入集成测试脚本，使用临时 MySQL 容器。
- 不使用公网服务。

### SQL migration 测试

- `shared/sql/init.sql` 包含新表和新列。
- 新增 `shared/sql/migrations/20260608_feedback_memory_profile_versioning.sql`。
- migration 使用 `information_schema.columns` 和 `information_schema.statistics` 保证可重复执行。
- 集成测试执行 migration 两次，确认不报错。

## 兼容性

- 旧的 `LatestUserProfileSnapshot` 可改为读取 active profile；若没有 active，则按最高 version 或 id 回退。
- 旧画像没有 version 时，migration 将其补为 version 1，并为每个用户最新记录设置 active。
- 旧反馈没有 idempotency key 时，migration 可用 `run_id` 回填。
- `ProcessFeedbackResponse` 需要新增字段时，保持现有字段编号不变，只追加新字段。
- 如果短期内不重新生成 protobuf，可先把结构化反馈和 diff 通过 JSON 字符串字段传递，但最终实现应补齐 proto 契约。

## 非目标

- 不引入新的独立 Memory Service。
- 不把推荐解释交给 LLM 重新生成。
- 不要求本轮实现后台常驻 worker；补偿任务可以先通过 API 或脚本触发重试。
- 不要求真实 Milvus/Neo4j 集成测试成为默认测试；默认仍使用本地内存或 mock。
- 不删除旧画像版本。

## 实施顺序建议

1. 先补 Python `FeedbackAgent` 和 `MemoryAgent` 的结构化反馈、权重合并、diff 和失败日志测试。
2. 再补 proto 追加字段和 Go/Python 转换。
3. 再补 MySQL schema、migration、store 版本化读写和幂等写入。
4. 再改 harness 的反馈幂等、画像版本插入、补偿任务创建。
5. 最后补 HTTP API、推荐解释持久化、画像重建任务和 README。

## 自检

- 覆盖了用户提出的 10 条要求和 5 个新增 API/任务。
- 明确了原始反馈、结构化反馈、画像版本、diff、回滚和补偿任务的持久化位置。
- 明确了兴趣权重范围与短长期合并策略。
- 明确了正反馈、负反馈和风格偏好的不同策略。
- 明确了 Milvus、Neo4j、MySQL 失败后的处理方式。
- 明确了并发反馈、重复反馈和部分失败的测试方向。
