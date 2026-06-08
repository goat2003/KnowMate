# 统一可观测性设计

日期：2026-06-08

## 目标

为 KnowMate 全系统增加统一可观测性，让 GoFrame 后端、Python Agent、MCP Server 在同一套链路、指标和日志语义下运行。

本设计覆盖：

- OpenTelemetry tracing / metrics 接入
- `trace_id` 与 `run_id` 跨 GoFrame、Python Agent、MCP Server 关联
- gRPC 和 MCP 调用 trace context 自动或显式传播
- 结构化 JSON 日志
- 敏感字段脱敏
- Prometheus Metrics
- Grafana Dashboard
- Prometheus 告警规则与 Alertmanager 配置
- `docker-compose.yml` 观测组件
- 运维文档与离线优先验证策略

## 已确认决策

- 采用“标准生产观测栈”方案：OpenTelemetry + Prometheus + Grafana + Alertmanager + Jaeger + OTel Collector。
- `run_id` 继续作为业务任务 ID，由 GoFrame 生成并传递到 Python Agent 和 MCP 调用日志。
- `trace_id` 使用 OpenTelemetry/W3C TraceContext 自动生成和传播，用于跨进程分布式追踪。
- `trace_id` 与 `run_id` 在日志和 span attributes 中同时出现，但职责不混用：trace 负责调用链路，run 负责业务任务归因。
- gRPC 通过 OpenTelemetry instrumentation 传播 trace context。
- MCP HTTP 通过 `traceparent` / `tracestate` headers 传播 trace context；memory/stdio MCP 在当前 Python context 内创建子 span。
- Prometheus label 只使用低基数字段，不把 `run_id`、`trace_id`、文章正文、feedback 正文、prompt、完整 LLM 响应放入 label。
- 日志统一 JSON 输出到 stdout，方便 Docker、CI 和后续日志采集系统接入。
- 本轮不引入 Loki、Tempo、Promtail、node exporter、MySQL exporter；这些作为后续增强。

## 现状与问题

当前系统已经具备部分业务可追踪基础：

- GoFrame `Harness` 创建 `run_id`，并写入 `run_logs`、`task_runs`、`task_steps`。
- Python Agent 的 gRPC 请求和响应已经携带 `run_id`。
- MCP 调用日志通过 `McpCallLog` 回传并写入 `mcp_call_logs`。
- Python `BaseMcpClient` 已有 `redact_sensitive`，并有敏感字段脱敏测试。
- Docker Compose 已包含 GoFrame、Python Agent、多个 MCP Server、MySQL、Milvus/Neo4j production profile。

主要缺口：

- 没有统一 `trace_id`，跨 Go/Python/MCP 的一次任务无法在 tracing 系统中串起来。
- GoFrame、Python Agent、MCP Server 日志格式不统一，日志里缺少稳定的 `trace_id` / `span_id` / `run_id` 字段。
- Prometheus metrics 未覆盖任务、抓取、Agent、gRPC、MCP、LLM、推荐、反馈等核心指标。
- 缺少可版本化的 Grafana Dashboard 和告警规则。
- Docker Compose 没有 OTel Collector、Prometheus、Grafana、Jaeger、Alertmanager。
- LLM token/cost、推荐保留率、推文生成成功率等业务指标缺少统一定义。

## 方案对比

### 方案一：最小可上线

只增加 `/metrics`、JSON 日志、基础 trace context 传播、Prometheus 和 Grafana。

优点：

- 改动小。
- 能快速看到核心指标和 JSON 日志。

缺点：

- 分布式 tracing 体验弱。
- MCP/LLM 链路仍需要从日志和 metrics 人工拼接。
- 后续补 tracing 时会再次改动同一批边界代码。

### 方案二：标准生产观测栈

GoFrame、Python Agent、MCP Server 全部接入 OpenTelemetry；gRPC 自动传播 trace context；MCP 调用在客户端和服务端边界显式传递；Prometheus scrape metrics；traces 通过 OTel Collector 进入 Jaeger；Grafana 自动加载 Dashboard；Prometheus 评估告警规则并发送 Alertmanager。

优点：

- 覆盖本轮所有目标。
- 能把 `HTTP /runs/articles -> GoFrame Harness -> gRPC -> Python workflow -> MCP tool -> LLM/存储` 串成一条 trace。
- 改动集中在现有边界：GoFrame handler/harness/grpcclient、Python grpc_server/workflow/mcp/llm、MCP common server。
- 不引入完整日志平台，运维复杂度可控。

这是本设计选定方案。

### 方案三：深度可观测平台

在方案二基础上加入 Loki/Promtail、Tempo、exemplar、容器/数据库 exporter、日志采集 pipeline。

优点：

- 生产观测能力更完整。
- 日志、指标、trace 查询体验更统一。

缺点：

- 一次性引入组件过多。
- 当前仓库还处在本地可验证和离线优先阶段，部署与维护成本偏高。

本轮不采用。

## 总体架构

```text
Client / operator
  -> GoFrame HTTP API
     -> HTTP middleware extracts or starts trace
     -> Harness creates or reuses run_id
     -> crawler fetch and persistence spans
     -> gRPC client injects trace context
        -> Python Agent gRPC server extracts trace context
           -> ArticleWorkflow / Feedback workflow spans
              -> Agent spans: filter / summary / rewrite / check / memory
              -> LLM spans and metrics
              -> MCP client spans
                 -> MCP HTTP headers carry traceparent
                    -> MCP Server extracts context
                    -> MCP tool spans and metrics

All services
  -> JSON stdout logs with trace_id/span_id/run_id
  -> /metrics scraped by Prometheus
  -> OTLP traces sent to OTel Collector
  -> Jaeger stores traces
  -> Grafana reads Prometheus and links trace_id to Jaeger
  -> Prometheus sends alerts to Alertmanager
```

## Trace 与 Run Context

### 统一字段

- `trace_id`：OpenTelemetry trace id，自动生成，跨进程传播。
- `span_id`：当前 span id，用于日志和 trace 关联。
- `run_id`：业务任务 ID，用于文章任务、反馈任务、画像重建任务归因。
- `task_type`：`articles`、`feedback`、`profile_rebuild`。
- `service.name`：`goframe-backend`、`python-agent`、`embedding-mcp`、`fetch-mcp`、`milvus-mcp`、`neo4j-mcp`。

### GoFrame

新增 `goframe-backend/internal/observability` 包：

- 初始化 OpenTelemetry tracer provider、meter provider、propagator。
- 设置 W3C TraceContext + Baggage propagator。
- 提供 HTTP middleware：提取 incoming trace context，创建 request span，把 context 传给 handler。
- 提供 `WithRunID` / `RunIDFromContext`。
- 提供 `SpanAttributesForRun`，统一添加 `run_id`、`task_type`。
- 提供 JSON 日志 handler 和脱敏函数。
- 提供 Prometheus `/metrics` handler。

GoFrame 链路：

- `main.go` 启动时初始化 observability，并在退出时 shutdown provider。
- `handler.Register` 注册 HTTP middleware 和 `/metrics`。
- `RunArticles`、`Feedback`、`RebuildProfile` 创建任务级 span。
- `grpcclient.New` 使用 `otelgrpc.NewClientHandler` 注入 trace context。
- `Harness` 在抓取、入库、gRPC 调用、保存 posts、写 run log 等步骤创建子 span。

### Python Agent

新增 `python-agent/app/observability.py`：

- 初始化 OpenTelemetry tracer provider、meter provider、propagator。
- 配置 OTLP exporter 和 Prometheus metrics。
- 配置 JSON logging formatter，自动注入 `trace_id`、`span_id`、`run_id`、`service`。
- 提供 `run_context` contextvar，保存当前 `run_id`。
- 提供 `redact_sensitive`，复用并扩展现有脱敏语义。
- 提供 metrics helper，避免业务文件直接管理底层 Counter/Histogram。

Python Agent 链路：

- `server.py` 启动时初始化 observability。
- `grpc_server.create_server` 使用 gRPC instrumentation，自动提取 trace context。
- `ProcessArticles` / `ProcessFeedback` 设置当前 `run_id`，创建 RPC 内部业务 span。
- `ArticleWorkflow` 对每个 Agent 执行创建 span 并记录 Agent metrics。
- `LLMTool` 对每次 LLM 调用记录 token/cost metrics 和 span attributes。
- `OfficialMcpTransport` 调用 HTTP MCP 时注入 `traceparent` / `tracestate`。

### MCP Server

新增 `mcp-servers/common/observability.py`：

- 初始化 MCP Server 的 OTel、Prometheus metrics、JSON logging。
- 提供 Starlette/FastMCP 可用的 context 提取辅助函数。
- 提供 tool 调用 wrapper，统一记录 span、metrics、脱敏日志。

MCP Server 链路：

- `simple_http_mcp.create_server` 初始化 observability。
- `/metrics` 通过 Starlette custom route 暴露。
- `call_tool` 从当前请求 headers 提取 trace context，创建 `mcp.tool` span。
- 工具异常按 `status=failed` 和 `error_type` 记录 metrics。

## Metrics 设计

命名统一使用 `knowmate_` 前缀。Histogram 单位使用 seconds；Counter 使用 `_total` 后缀；Gauge 用于当前状态或比率。

### GoFrame 指标

抓取文章数量和失败率：

- `knowmate_crawler_articles_total{source,type,status}`
- `knowmate_crawler_source_runs_total{source,type,status}`
- `knowmate_crawler_fetch_duration_seconds{source,type,status}`

任务完成率：

- `knowmate_task_runs_total{task_type,status}`
- `knowmate_task_duration_seconds{task_type,status}`
- `knowmate_task_steps_total{task_type,step,status}`

gRPC 调用延迟和失败率：

- `knowmate_grpc_client_requests_total{method,status_code}`
- `knowmate_grpc_client_duration_seconds{method,status_code}`

推荐保留率、推文生成成功率、用户反馈数量：

- `knowmate_recommendation_items_total{decision}`
- `knowmate_recommendation_retention_ratio`
- `knowmate_posts_generated_total{status}`
- `knowmate_feedback_received_total{feedback_type,status}`

### Python Agent 指标

每个 Agent 执行次数、延迟和失败率：

- `knowmate_agent_runs_total{agent,status}`
- `knowmate_agent_duration_seconds{agent,status}`

gRPC 服务端延迟和失败率：

- `knowmate_grpc_server_requests_total{method,status_code}`
- `knowmate_grpc_server_duration_seconds{method,status_code}`

LLM token 使用量和成本：

- `knowmate_llm_tokens_total{provider,model,task,token_type}`
- `knowmate_llm_cost_usd_total{provider,model,task}`
- `knowmate_llm_requests_total{provider,model,task,status}`
- `knowmate_llm_duration_seconds{provider,model,task,status}`

推荐和推文：

- `knowmate_recommendation_items_total{decision}`
- `knowmate_post_generation_total{status}`

### MCP 指标

MCP Tool 调用延迟和失败率：

- `knowmate_mcp_tool_calls_total{server,tool,status}`
- `knowmate_mcp_tool_duration_seconds{server,tool,status}`
- `knowmate_mcp_tool_failures_total{server,tool,error_type}`

### Label 规则

允许进入 label：

- `service`
- `method`
- `status`
- `status_code`
- `task_type`
- `step`
- `agent`
- `server`
- `tool`
- `provider`
- `model`
- `source`
- `type`
- `decision`
- `feedback_type`
- `error_type`

禁止进入 label：

- `run_id`
- `trace_id`
- `span_id`
- URL 全量
- 用户 ID
- feedback 正文
- 文章正文
- prompt
- LLM response
- token、password、secret、DSN

## 日志设计

日志统一输出 JSON，每行一条。

基础字段：

```json
{
  "time": "2026-06-08T12:00:00Z",
  "level": "info",
  "service": "python-agent",
  "logger": "app.workflow.graph",
  "message": "agent completed",
  "trace_id": "6f4...",
  "span_id": "2a1...",
  "run_id": "articles-20260608120000-a1b2c3d4"
}
```

错误日志字段：

- `error_type`
- `error_message`
- `status`
- `task_type`
- `agent`
- `mcp_server`
- `mcp_tool`

脱敏后才允许写入：

- request payload 摘要
- response payload 摘要
- error message
- provider headers
- MCP request/response JSON
- LLM provider response metadata

## 脱敏设计

Python 复用并扩展 `python-agent/app/mcp/base_client.py` 中现有 `redact_sensitive`；后续迁移到 `app/observability.py` 并从 `base_client.py` 复用。

Go 新增同等语义的 `observability.RedactSensitive`。

敏感 key：

- `api_key`
- `apikey`
- `authorization`
- `access_token`
- `refresh_token`
- `token`
- `password`
- `secret`
- `credential`
- `cookie`
- `set-cookie`
- `mysql_dsn`
- `dsn`

敏感文本模式：

- `Bearer <token>`
- `api_key=<value>`
- `authorization=<value>`
- `access_token=<value>`
- `refresh_token=<value>`
- `password=<value>`
- `secret=<value>`
- `cookie=<value>`
- MySQL DSN 中 `user:password@tcp(...)` 的 password 段

敏感正文处理：

- 文章正文只记录 `content_length`、`content_hash`。
- feedback 正文只记录 `feedback_length`、`feedback_hash`、`feedback_type`。
- prompt 只记录 `prompt_length`、`prompt_hash`、`task`。
- LLM response 只记录 `response_length`、`response_hash`、`finish_reason`、token usage。

## OpenTelemetry 配置

统一环境变量：

- `OTEL_ENABLED=true`
- `OTEL_SERVICE_NAME`
- `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317`
- `OTEL_EXPORTER_OTLP_PROTOCOL=grpc`
- `OTEL_TRACES_SAMPLER=parentbased_traceidratio`
- `OTEL_TRACES_SAMPLER_ARG=1.0`
- `OTEL_RESOURCE_ATTRIBUTES=deployment.environment=local,service.namespace=knowmate`

GoFrame 默认：

- `OTEL_SERVICE_NAME=goframe-backend`
- Prometheus metrics path：`/metrics`

Python Agent 默认：

- `OTEL_SERVICE_NAME=python-agent`
- gRPC port：`50051`
- metrics port：`9101`

MCP Server 默认：

- `OTEL_SERVICE_NAME` 等于 `MCP_SERVER`
- metrics path：`/metrics`
- HTTP port 沿用现有 7001-7004

## Docker Compose 设计

新增服务：

- `otel-collector`：接收 OTLP traces/metrics/logs，traces 转发到 Jaeger。
- `jaeger`：本地 trace 查询 UI。
- `prometheus`：scrape GoFrame、Python Agent、MCP Server、OTel Collector。
- `grafana`：展示 Dashboard。
- `alertmanager`：接收 Prometheus 告警。

新增目录：

```text
observability/
  otel-collector.yml
  prometheus.yml
  alerts.yml
  alertmanager.yml
  grafana/
    provisioning/
      datasources/
        prometheus.yml
      dashboards/
        dashboards.yml
    dashboards/
      knowmate-overview.json
```

端口约定：

- Prometheus：`9090`
- Grafana：`3000`
- Alertmanager：`9093`
- Jaeger UI：`16686`
- OTel Collector OTLP gRPC：`4317`
- OTel Collector OTLP HTTP：`4318`
- Python Agent metrics：`9101`

## Grafana Dashboard

Dashboard 名称：`KnowMate Observability Overview`

面板分组：

1. 任务总览
   - 任务完成率
   - 任务失败率
   - 任务 P95 耗时
   - 当前 running/pending 任务数量

2. 抓取质量
   - 抓取文章数量
   - 来源级失败率
   - source run 状态分布
   - fetch P95 耗时

3. Agent / LLM
   - Agent 调用次数
   - Agent 失败率
   - Agent P95 耗时
   - LLM token 使用量
   - LLM 成本

4. gRPC / MCP
   - gRPC client/server 失败率
   - gRPC P95 耗时
   - MCP Tool 调用次数
   - MCP Tool 失败率
   - MCP Tool P95 耗时

5. 推荐与反馈
   - 推荐保留率
   - 推文生成成功率
   - 用户反馈数量
   - feedback 处理失败率

## 告警规则

Prometheus `observability/alerts.yml` 包含：

- `KnowMateServiceDown`：任一核心服务 `up == 0` 持续 2 分钟。
- `KnowMateTaskFailureRateHigh`：5 分钟内任务失败率超过 20%。
- `KnowMateCrawlerFailureRateHigh`：5 分钟内抓取失败率超过 30%。
- `KnowMateGrpcClientFailureRateHigh`：5 分钟内 gRPC client 失败率超过 10%。
- `KnowMateGrpcServerLatencyHigh`：gRPC server P95 超过 10 秒持续 5 分钟。
- `KnowMateMcpToolFailureRateHigh`：MCP Tool 失败率超过 15% 持续 5 分钟。
- `KnowMateMcpToolLatencyHigh`：MCP Tool P95 超过 8 秒持续 5 分钟。
- `KnowMateAgentFailureRateHigh`：Agent 失败率超过 10% 持续 5 分钟。
- `KnowMateLlmCostSpike`：1 小时 LLM 成本超过配置阈值。
- `KnowMateRecommendationRetentionLow`：推荐保留率低于 20% 持续 15 分钟。
- `KnowMatePostGenerationFailureHigh`：推文生成失败率超过 10% 持续 10 分钟。
- `KnowMateFeedbackProcessingFailureHigh`：反馈处理失败率超过 10% 持续 10 分钟。

Alertmanager 默认使用本地空接收器，配置为本地开发不主动发外部通知；生产环境通过环境或覆盖文件配置 Slack、企业微信、邮件等接收器。

## 运维文档

更新 `README.md`，新增“可观测性”章节：

- 如何启动观测栈。
- 各服务 metrics URL。
- Prometheus、Grafana、Jaeger、Alertmanager 访问地址。
- 如何按 `run_id` 查业务日志。
- 如何按 `trace_id` 查 Jaeger trace。
- 常见告警含义与排查路径。
- 如何调整 LLM 成本告警阈值。
- 本地 Docker 端口冲突处理。

新增 `docs/observability.md`：

- 指标字典。
- 日志字段字典。
- trace/span 命名规范。
- 脱敏规则。
- Dashboard 面板说明。
- 告警规则说明。
- 本地验证命令。

## 测试策略

### Go

新增测试：

- `goframe-backend/internal/observability/observability_test.go`
  - `RedactSensitive` 能脱敏 token、password、DSN。
  - `WithRunID` / `RunIDFromContext` 能稳定传递。
  - JSON 日志字段包含 `trace_id`、`span_id`、`run_id`。

- `goframe-backend/internal/grpcclient/client_test.go`
  - 使用本地 bufconn 或测试 server 验证 gRPC metadata 中有 trace context。
  - 验证 gRPC metrics 记录 method/status/duration。

- `goframe-backend/internal/logic/harness/*_test.go`
  - 现有任务测试补充 metrics 断言，确认 articles、posts、tasks 指标递增。

### Python Agent

新增测试：

- `python-agent/tests/test_observability.py`
  - JSON formatter 输出 trace/log/run 字段。
  - `redact_sensitive` 覆盖 key、Bearer、DSN。
  - metrics helper 正确记录 Agent、LLM、gRPC 指标。

- `python-agent/tests/test_grpc_observability.py`
  - gRPC request 带 `traceparent` 时服务端 span 使用同一 trace。
  - `ProcessArticles` 和 `ProcessFeedback` 设置 run context。

- `python-agent/tests/test_mcp_observability.py`
  - `OfficialMcpTransport` HTTP 调用注入 `traceparent`。
  - `BaseMcpClient.call_tool` 记录 MCP metrics。

### MCP Server

新增测试：

- `mcp-servers/tests/test_observability.py`
  - `/metrics` 可访问。
  - `call_tool` 记录 tool calls 和 duration。
  - 请求 headers 中的 `traceparent` 被提取并写入子 span。
  - 工具异常记录 failed status 和 error_type。

### 配置校验

新增脚本：

- `scripts/check_observability_config.ps1`
  - 校验 `observability/prometheus.yml`、`alerts.yml`、`alertmanager.yml` 是合法 YAML。
  - 校验 Grafana provisioning 文件存在。
  - 校验 Dashboard JSON 可解析。
  - 校验 docker-compose 中 observability 服务和端口存在。

### 回归命令

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
go test ./... -count=1
go vet ./...
python -m pytest python-agent/tests mcp-servers/tests
powershell -ExecutionPolicy Bypass -File scripts/check_observability_config.ps1
```

Docker smoke 仍然按环境问题和代码问题区分：镜像拉取 EOF、宿主 3306 端口冲突先归类为环境问题；本地可通过 `MYSQL_PORT` 调整。

## 实施切分

1. 共享约定
   - Go/Python 增加 trace/run context helper。
   - Go/Python/MCP 增加脱敏测试和实现。
   - JSON 日志先接入 stdout。

2. GoFrame OTel 与 metrics
   - 新增 `internal/observability`。
   - HTTP middleware、`/metrics`、gRPC client instrumentation。
   - Harness/crawler/task/post/feedback 业务 metrics。

3. Python Agent OTel 与 metrics
   - 新增 `app/observability.py`。
   - gRPC server instrumentation。
   - Agent/LLM/推荐/推文 metrics。

4. MCP trace propagation 与 metrics
   - `OfficialMcpTransport` 注入 trace headers。
   - `simple_http_mcp.py` 提取 context 并记录 tool metrics。
   - MCP Server `/metrics`。

5. 业务指标补齐
   - LLM token/cost。
   - 推荐保留率。
   - 推文生成成功率。
   - 用户反馈数量。
   - 任务完成率。

6. 观测组件与文档
   - `docker-compose.yml` 增加 OTel Collector、Prometheus、Grafana、Jaeger、Alertmanager。
   - 增加 Prometheus、Grafana、Alertmanager、Collector 配置。
   - 增加 Dashboard JSON。
   - 更新 README 和新增 `docs/observability.md`。
   - 增加配置校验脚本。

## 非目标

- 不把日志写入数据库。
- 不新增 Loki/Tempo/Promtail。
- 不新增 Kubernetes/Helm 部署。
- 不引入外部 SaaS APM。
- 不把 `run_id`、`trace_id` 放入 Prometheus label。
- 不记录完整文章正文、feedback 正文、prompt、LLM response。

## 风险与缓解

- 风险：metrics label 基数过高导致 Prometheus 压力上升。
  - 缓解：严格禁止 `run_id`、`trace_id`、URL、用户 ID、正文进入 label。

- 风险：OTel SDK 初始化影响本地测试。
  - 缓解：提供 `OTEL_ENABLED=false`，默认 exporter 失败不阻断主流程；测试使用内存 exporter 或禁用真实网络 exporter。

- 风险：日志脱敏覆盖不完整。
  - 缓解：Go/Python 都增加 key、Bearer、DSN、嵌套 dict/list、MCP request/response 的单元测试。

- 风险：MCP SDK 对 request headers 的访问路径变化。
  - 缓解：优先在 `simple_http_mcp.py` 的 Starlette custom route / ServerRequestContext 边界处理，保持失败时不影响 tool 调用。

- 风险：Dashboard JSON 手写容易损坏。
  - 缓解：增加 JSON 解析校验脚本；Dashboard 第一版只使用 Prometheus 数据源，不依赖外部插件。

## 验收标准

- GoFrame、Python Agent、MCP Server 日志均为 JSON，并包含 `service`、`trace_id`、`span_id`，任务链路包含 `run_id`。
- 从一次 `POST /runs/articles` 能在 Jaeger 中看到 GoFrame -> Python Agent -> MCP Tool 的连续 trace。
- Prometheus 能 scrape GoFrame、Python Agent、MCP Server、OTel Collector。
- Grafana Dashboard 自动加载并展示任务、抓取、Agent/LLM、gRPC/MCP、推荐反馈指标。
- 告警规则能被 Prometheus 加载。
- 敏感字段测试覆盖并通过，日志和 MCP call logs 中不出现明文 token/password/DSN。
- 离线测试通过，不依赖公网 API。
