# KnowMate 架构说明

> 原文镜像：`ARCHITECTURE.md`
>
> 原文件已以中文为主；本镜像保留命令、路径、代码块和协议字段原样。


## 总览

KnowMate 是一个个性化知识内容处理系统。GoFrame Backend 负责 HTTP API、任务编排、数据库持久化和 Markdown 输出；Python Agent 负责筛选、总结、改写、检查和反馈画像更新；MCP Server 负责外部工具边界，包括网页抓取、embedding、Milvus 向量记忆和 Neo4j 兴趣图。

```text
Web Admin
  -> GoFrame Backend HTTP API
    -> MySQL: articles/posts/run_logs/task_runs/user_profile_snapshot/mcp_call_logs
    -> Python Agent gRPC
      -> Filter Agent
      -> Summary Agent
      -> Rewrite Agent
      -> Check Agent
      -> Feedback Agent / Memory Agent
      -> MCP Client policy and transport
        -> embedding-mcp -> OpenAI-compatible embedding or memory
        -> fetch-mcp -> webpage fetch and main-content extraction
        -> milvus-mcp -> Milvus or memory vector store
        -> neo4j-mcp -> Neo4j or memory graph store
```

## 服务

### GoFrame Backend

- 目录：`goframe-backend/`
- 入口：`main.go`
- 端口：`8080`
- 健康检查：`GET /health`
- 指标：`GET /metrics`
- 主要职责：抓取源读取、文章入库、任务状态机、gRPC 调用、结果入库、Markdown 输出、管理后台 API。

### Python Agent

- 目录：`python-agent/`
- 入口：`server.py` 或 `python -m app.main`
- 端口：`50051`
- 指标：`9101`
- 主要职责：ArticleWorkflow、推荐排序、LLM 结构化输出、MCP 调用策略、反馈画像更新。

### MCP Servers

- 目录：`mcp-servers/`
- 通用入口：`mcp-servers/Dockerfile` 通过 `MCP_SERVER` 选择子服务。
- `embedding-mcp`: `7001`
- `fetch-mcp`: `7002`
- `milvus-mcp`: `7003`
- `neo4j-mcp`: `7004`

每个 MCP Server 暴露 `/health` 和 `/metrics`。生产 provider 不可用时健康检查返回 `503`，但服务进程保持存活，方便依赖恢复。

### Web Admin

- 目录：`web-admin/`
- 构建：Vite + React
- 生产服务：非 root Nginx，端口 `8080`
- 主要流程：系统概览、手动抓取、任务详情/重试、文章/推文查看、反馈提交、画像历史、MCP 调用日志。

## 数据流

### 文章处理

1. 管理后台或调用方请求 `POST /runs/articles`。
2. GoFrame 创建 `task_runs` 和 `task_steps`。
3. Crawler 从 `crawler.sources` 抓取 RSS/Atom/arXiv/GitHub Release/HuggingFace/mock。
4. GoFrame 去重并保存 `articles`，记录 `crawl_source_runs`。
5. GoFrame 调用 Python Agent `ProcessArticles`。
6. Python Agent 执行筛选、总结、改写和检查，并按 MCP Policy 调用工具。
7. GoFrame 保存 `posts`、`run_logs`、`mcp_call_logs`，写出 Markdown。
8. 管理后台通过 `/runs`、`/posts`、`/mcp-call-logs` 查看结果。

### 反馈与用户画像

1. 调用 `POST /feedback`。
2. GoFrame 保存原始 `feedback_logs`。
3. Python Agent `ProcessFeedback` 提取结构化反馈。
4. Memory Agent 更新画像字段，并按策略写入 Milvus/Neo4j。
5. GoFrame 生成新的 `user_profile_snapshot.version`，保留 `diff_json`。
6. 若外部记忆服务失败，写入补偿任务，后续可重试。

## 数据库

新环境使用 `shared/sql/init.sql` 初始化。已有环境按顺序执行：

- `shared/sql/migrations/20260606_production_crawler.sql`
- `shared/sql/migrations/20260608_feedback_memory_profile_versioning.sql`
- `shared/sql/migrations/20260608_harness_task_control.sql`

生产部署不让多个应用副本自动并发执行 DDL，而是用：

- Compose: `migration-runner` 服务
- Kubernetes: `migration-runner` Job

该策略既满足自动执行，也便于观察、重试和回滚。

## 部署

### Docker Compose

- 本地开发：`docker-compose.yml`
- 生产候选：`docker-compose.prod.yml`
- 配置示例：`configs/env/dev.env`、`configs/env/test.env`、`configs/env/prod.env.example`

所有应用镜像都使用非 root 用户，并配置 Docker `HEALTHCHECK`。

### Kubernetes

普通 manifests 位于 `deploy/kubernetes/`：

- `namespace.yaml`
- `app-config.yaml`
- `secrets.example.yaml`
- `mysql.yaml`
- `migration-job.yaml`
- `mcp-servers.yaml`
- `python-agent.yaml`
- `goframe-backend.yaml`
- `web-admin.yaml`
- `observability.yaml`

这些 manifests 提供生产候选基线：非 root、readiness/liveness probe、滚动更新、ConfigMap/Secret、migration Job。Ingress、TLS、HPA、NetworkPolicy 和托管数据库接入列入下一版本。

## 安全

- GoFrame HTTP API 支持 `GOFRAME_API_TOKEN`。
- GoFrame 调 Python Agent 时使用 `AGENT_GRPC_AUTH_TOKEN`。
- Python Agent gRPC Server 支持 `Authorization: Bearer` 或 `x-api-key` metadata。
- MCP 调用先经过 `python-agent/app/mcp/policy.py` 权限判断，未授权工具返回 `MCP_PERMISSION_DENIED`，不会发到 MCP transport。
- MCP 请求/响应日志会脱敏 `api_key`、`authorization`、`token`、`password`、`cookie` 等敏感字段。
- 容器以非 root 用户运行，Kubernetes 设置 `allowPrivilegeEscalation: false` 和 `seccompProfile: RuntimeDefault`。

## 可观测性

- Metrics: GoFrame `/metrics`、Python Agent `9101/metrics`、MCP `/metrics`。
- Traces: OpenTelemetry Collector 可导出到 Jaeger 或平台 APM。
- Logs: 运行日志写 stdout/stderr，业务审计写 MySQL。
- Alerts: `observability/alerts.yml` 提供告警起点。

## 任务恢复

GoFrame Harness 使用 `task_runs`、`task_steps`、`partial_result_json` 持久化任务状态。服务重启时会把中断任务恢复到可重试状态，管理后台可调用 `/runs/{run_id}/retry`。

## 已知架构限制

- 当前 Harness 并发控制主要在单进程内实现，多副本下仍依赖数据库状态降低重复执行风险，后续需要分布式锁。
- Kubernetes manifests 没有内置 Ingress/TLS/外部 Secret 管理。
- MySQL/Milvus/Neo4j 的高可用依赖部署平台或外部托管方案。
- LLM 生产质量依赖外部模型与提示词评估，默认 fixture 验收不能证明真实模型效果。
