# 反馈记忆画像版本化实施计划

> 原文镜像：`docs/superpowers/plans/2026-06-08-feedback-memory-profile-versioning.md`
>
> 本文件为中文结构化译本。原文中的大段测试代码、命令和生成代码说明以原文件为准；本译本保留完整任务路线、文件范围、步骤顺序和验收意图。

> **给 agentic workers：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施本计划。步骤使用 checkbox（`- [ ]`）语法追踪。

**目标：** 完成 Feedback Agent、Memory Agent 与 GoFrame 用户画像更新链路，使反馈处理幂等、画像可版本化、可追踪、可回滚，并支持失败补偿与推荐解释查询。

**架构：** Python Agent 负责结构化反馈抽取、画像权重合并、diff 生成与 MCP 调用；GoFrame 负责原始反馈、结构化反馈、画像版本、补偿任务、HTTP API 和 MySQL 审计。MySQL schema 使用 `init.sql` 加独立 migration 双轨更新，测试默认使用 mock、fake store 和本地 fixture，不依赖公网。

**技术栈：** GoFrame/Go、Python 3、grpcio/protobuf、MySQL 8、Milvus/Neo4j MCP mock transport、PowerShell test scripts。

## 工作区约束

- 每个任务开始前运行 `git status --short`。
- 只读取或修改该任务列出的文件。
- 不使用 `git add .`。
- 每次提交只暂存当前任务文件。
- 不删除或回退用户已有改动。
- 默认文档和注释使用中文，代码标识使用英文。

## 文件结构

### Python Agent

- 修改 `python-agent/app/tools/llm_tool.py`：扩展 `FeedbackLLMOutput`，增加 `structured_feedback`，并让 mock/fallback feedback 输出结构化三类信号。
- 修改 `python-agent/app/agents/feedback_agent.py`：将 `structured_feedback` 写入 workflow state。
- 修改 `python-agent/app/agents/memory_agent.py`：增加画像合并策略、权重 clamp、diff 生成和结构化反馈兼容解析。
- 修改 `python-agent/app/workflow/state.py`：增加 `structured_feedback`、`profile_diff` typed fields。
- 修改 `python-agent/app/workflow/graph.py`：`process_feedback` 返回 `structured_feedback` 和 `profile_diff`。
- 修改 `python-agent/app/grpc_server.py`：处理新 proto 字段和 Python dict 之间的转换。
- 测试 `python-agent/tests/test_workflow.py`：覆盖结构化反馈、权重合并、diff、并发幂等缓存。

### Protobuf

- 修改 `proto/agent.proto` 与 `shared/proto/agent.proto`：只追加字段，不改变现有字段编号。
- 重新生成 Python 与 Go protobuf 文件。
- 更新 `goframe-backend/internal/agentpb/proto_contract_test.go` 与 `scripts/check_proto_contract.ps1`。

### GoFrame Model/Store/Harness/API

- 修改 `goframe-backend/internal/model/model.go`：增加用户画像、反馈记录、补偿任务、推荐解释等模型。
- 修改 `goframe-backend/internal/store/mysql.go`：增加反馈幂等、画像 active/history/rollback、补偿任务、推荐解释 metadata 查询。
- 修改 `goframe-backend/internal/logic/harness/harness.go`：把 `ProcessFeedback` 调整为幂等版本化流程，增加补偿任务创建和 profile rebuild。
- 修改 `goframe-backend/internal/handler/handler.go`：增加 `/profile`、`/profile/history`、`/profile/rollback`、`/recommendations/explain`、`/profile/rebuild`。
- 增加或更新 store、harness、handler 测试。

### SQL/Docs/Scripts

- 修改 `shared/sql/init.sql`。
- 新建 `shared/sql/migrations/20260608_feedback_memory_profile_versioning.sql`。
- 修改 `scripts/integration_test.ps1`、`README.md`、`shared/config/README.md`。

## Task 1：Python 结构化反馈契约

**文件：** `llm_tool.py`、`feedback_agent.py`、`workflow/state.py`、`workflow/graph.py`、`python-agent/tests/test_workflow.py`

- [ ] 编写失败测试，要求 feedback workflow 输出结构化反馈字段。
- [ ] 运行测试确认失败点来自缺少契约。
- [ ] 扩展 `FeedbackLLMOutput`，兼容 mock、fallback 和 LLM JSON 修复路径。
- [ ] 将 `FeedbackAgent` state 写入 `structured_feedback`。
- [ ] 保持 `MemoryAgent` 对旧 `extracted_feedback` 的兼容。
- [ ] 重新运行聚焦测试。
- [ ] 仅提交当前任务文件。

## Task 2：MemoryAgent 权重合并、Clamp 与 Diff

**文件：** `memory_agent.py`、`workflow/state.py`、`workflow/graph.py`、`test_workflow.py`

- [ ] 编写失败测试覆盖正反馈、负反馈、风格偏好、权重上限/下限和 diff 输出。
- [ ] 运行测试确认失败。
- [ ] 增加 helper，解析 snapshot、合并结构化反馈、限制权重范围。
- [ ] 增加结构化 merge 方法，生成 `profile_diff`。
- [ ] 在 `run` 中调用 merge 方法。
- [ ] 运行测试确认通过。
- [ ] 仅提交当前任务文件。

## Task 3：gRPC/protobuf 追加结构化反馈与 Diff 字段

**文件：** 两份 proto、生成文件、`grpc_server.py`、proto contract tests

- [ ] 编写失败的 Python gRPC 测试。
- [ ] 运行测试确认失败。
- [ ] 在 proto 中追加字段，保持已有字段编号稳定。
- [ ] 重新生成 Python protobuf stubs。
- [ ] 重新生成 Go protobuf stubs。
- [ ] 接入 Python gRPC dict 转换。
- [ ] 更新 proto contract 测试。
- [ ] 运行相关测试。
- [ ] 仅提交当前任务文件。

## Task 4：SQL Schema 与 Migration

**文件：** `shared/sql/init.sql`、新 migration、schema contract tests

- [ ] 编写 schema contract 失败测试。
- [ ] 运行测试确认失败。
- [ ] 更新 `shared/sql/init.sql`。
- [ ] 创建幂等 migration。
- [ ] 运行 schema contract 测试。
- [ ] 仅提交当前任务文件。

## Task 5：Store 模型、反馈幂等与画像版本读写

**文件：** `model.go`、`mysql.go`、store tests

- [ ] 编写纯 helper 测试，覆盖幂等 key、active snapshot、history、rollback、补偿任务模型。
- [ ] 运行测试确认失败。
- [ ] 增加模型类型。
- [ ] 增加 helper 函数。
- [ ] 增加 store method signatures。
- [ ] 运行 helper 测试。
- [ ] 仅提交当前任务文件。

## Task 6：Harness 反馈幂等、版本化和补偿任务

**文件：** `harness.go`、harness tests

- [ ] 编写 fake-store feedback 测试。
- [ ] 运行测试确认失败。
- [ ] 增加 feedback agent test hook。
- [ ] 扩展 articleStore interface。
- [ ] 修改 `ProcessFeedback` 流程：保存原始反馈、调用 Agent、写版本、记录补偿任务。
- [ ] 运行 harness 测试。
- [ ] 仅提交当前任务文件。

## Task 7：HTTP Profile、History、Rollback、Explanation、Rebuild APIs

**文件：** `handler.go`、handler tests、harness/store 支撑方法

- [ ] 编写 handler route 失败测试。
- [ ] 运行测试确认失败。
- [ ] 注册新增路由。
- [ ] 增加 request/response structs。
- [ ] 实现 handlers。
- [ ] 实现 `RebuildProfile` 最小流程。
- [ ] 运行 handler 测试。
- [ ] 仅提交当前任务文件。

## Task 8：推荐解释持久化

**文件：** post model、Insert/List posts、harness persist、解释查询

- [ ] 编写 metadata 失败测试。
- [ ] 给 `model.Post` 增加 `Metadata`。
- [ ] 更新 `InsertPost` / `ListPosts`。
- [ ] 在 `persistAgentResults` 中填充 metadata。
- [ ] 实现 explanation query。
- [ ] 运行测试。
- [ ] 仅提交当前任务文件。

## Task 9：Profile Rebuild Replay

**文件：** store query、harness rebuild、tests

- [ ] 编写 rebuild replay 失败测试。
- [ ] 运行测试确认失败。
- [ ] 增加 store query。
- [ ] 实现最小 Go replay。
- [ ] 运行测试。
- [ ] 仅提交当前任务文件。

## Task 10：Integration Script 与文档

**文件：** `scripts/integration_test.ps1`、`README.md`、`shared/config/README.md`

- [ ] 更新 integration script migration check。
- [ ] 更新 README API 文档，补充 Profile Memory APIs。
- [ ] 更新 shared config README。
- [ ] 运行 docs/script sanity checks。
- [ ] 仅提交当前任务文件。

## Task 11：验证

- [ ] 运行 Python 单元测试。
- [ ] 运行 Go 单元测试。
- [ ] 运行 Go vet。
- [ ] 运行聚焦 race tests。
- [ ] 运行 migration integration check。
- [ ] 审查最终 diff。

## 自检

- 反馈链路幂等，重复 feedback 不会重复更新画像。
- 每次画像更新产生版本与 diff，可查询历史并回滚。
- 补偿任务记录部分失败，便于后续重试。
- 推荐解释可从已持久化 metadata 查询。
- 原有 proto 字段兼容，新增字段只追加。
- 文档、migration 与测试命令同步更新。
