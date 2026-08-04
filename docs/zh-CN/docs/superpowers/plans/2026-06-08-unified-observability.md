# 统一可观测性实施计划

> 原文镜像：`docs/superpowers/plans/2026-06-08-unified-observability.md`
>
> 本文件为中文结构化译本。原文中的大段测试代码、配置片段和 dashboard JSON 以原文件为准；本译本保留完整任务路线、文件范围、步骤顺序和验收意图。

> **给 agentic workers：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施本计划。步骤使用 checkbox（`- [ ]`）语法追踪。

**目标：** 为 GoFrame、Python Agent、MCP Server 增加统一 OpenTelemetry tracing、结构化 JSON 日志、Prometheus Metrics、Grafana Dashboard、告警规则和运维文档。

**架构：** 新增 Go/Python/MCP 三套轻量 observability 边界模块，分别在 HTTP、gRPC、workflow、MCP tool、LLM 调用边界记录 span 和 metrics。`trace_id` 由 OpenTelemetry/W3C TraceContext 跨进程传播，`run_id` 继续作为业务任务 ID 写入 span attributes 和 JSON 日志；Prometheus scrape 各服务 `/metrics`，OTel Collector 接收 traces 并转发 Jaeger，Grafana 读取 Prometheus Dashboard，Alertmanager 接收 Prometheus 告警。

**技术栈：** GoFrame v2、Go OpenTelemetry、otelgrpc、Prometheus Go client、Python OpenTelemetry、prometheus-client、grpcio、MCP Python SDK FastMCP、Docker Compose、Prometheus、Grafana、Jaeger、Alertmanager、PowerShell 验证脚本。

## 文件结构

- 新建 GoFrame observability 模块，覆盖 OTel 初始化、Prometheus metrics、run context、JSON 日志字段和脱敏。
- 修改 GoFrame main、handler、gRPC client 和 harness，接入 middleware、`/metrics`、trace propagation 和业务指标。
- 新建 Python Agent observability 模块，覆盖 OTel、Prometheus metrics、JSON logging、run context 和脱敏。
- 修改 Python gRPC server、workflow、LLM tool、MCP client 和 SDK transport，记录 RPC/workflow/LLM/MCP 指标并传播 trace headers。
- 新建 MCP Server observability 模块，接入 tool wrapper、`/metrics` route 和 trace extraction。
- 新增 observability 配置：OTel Collector、Prometheus、Alertmanager、Grafana datasource/dashboard provisioning、KnowMate overview dashboard。
- 修改 `docker-compose.yml` 与 `.env.example`，增加观测组件和业务服务观测环境变量。
- 新建 `scripts/check_observability_config.ps1` 和 `docs/observability.md`。
- 更新 `README.md` 的可观测性启动、访问地址和验证说明。

## Task 1：Go Observability Foundation

**文件：** `goframe-backend/internal/observability/*`、`goframe-backend/go.mod`

- [ ] 编写失败的 Go observability tests，覆盖脱敏、run context、metrics handler 和 trace propagation 基础能力。
- [ ] 运行 Go observability tests，确认失败。
- [ ] 添加 Go OTel、OTLP exporter、Prometheus 相关依赖。
- [ ] 实现 Go observability helpers。
- [ ] 运行测试确认通过。
- [ ] 提交 Task 1。

## Task 2：GoFrame HTTP、gRPC 与业务 Metrics

**文件：** GoFrame handler、grpcclient、harness、main、相关测试

- [ ] 编写失败的 gRPC client trace propagation test。
- [ ] 运行 gRPC client test，确认失败。
- [ ] 实现 gRPC client instrumentation。
- [ ] 运行 gRPC client test。
- [ ] 编写失败的 GoFrame business metrics test。
- [ ] 运行 business metrics test，确认失败。
- [ ] 记录 GoFrame 业务 metrics，并初始化 observability。
- [ ] 运行 GoFrame tests。
- [ ] 提交 Task 2。

## Task 3：Python Observability Foundation

**文件：** `python-agent/app/observability.py`、requirements、server、tests

- [ ] 编写失败的 Python observability tests，覆盖 JSON logging、脱敏和 metrics。
- [ ] 运行 Python observability tests，确认失败。
- [ ] 添加 Python OTel 和 Prometheus client 依赖。
- [ ] 实现 Python observability module。
- [ ] 在启动时初始化 Python observability。
- [ ] 运行 Python observability tests。
- [ ] 提交 Task 3。

## Task 4：Python gRPC、Workflow 与 LLM Metrics

**文件：** Python gRPC server、workflow graph、LLM tool、相关测试

- [ ] 编写失败的 gRPC run context test。
- [ ] 运行测试确认失败。
- [ ] 实现 gRPC run context 和 RPC metrics。
- [ ] 运行 gRPC run context test。
- [ ] 编写失败的 workflow Agent metrics test。
- [ ] 运行 workflow Agent metrics test，确认失败。
- [ ] 对 workflow Agent 执行过程加 instrumentation。
- [ ] 对 LLM usage 加 instrumentation。
- [ ] 运行 Python Agent observability tests。
- [ ] 提交 Task 4。

## Task 5：MCP Client 与 Server Observability

**文件：** Python MCP client/transport、MCP common server、MCP tests

- [ ] 编写失败的 MCP client metrics 与 trace header tests。
- [ ] 运行 MCP client observability tests，确认失败。
- [ ] 实现 MCP client metrics 和 trace header 注入。
- [ ] 运行 MCP client observability tests。
- [ ] 编写失败的 MCP server observability tests。
- [ ] 运行 MCP server observability tests，确认失败。
- [ ] 实现 MCP server observability。
- [ ] 运行 MCP server tests。
- [ ] 提交 Task 5。

## Task 6：Observability Docker 与 Prometheus 配置

**文件：** observability YAML、docker-compose、`.env.example`、校验脚本

- [ ] 编写失败的 observability config validation script。
- [ ] 运行 config validation，确认失败。
- [ ] 添加 OTel Collector config。
- [ ] 添加 Prometheus 和 Alertmanager configs。
- [ ] 修改 `docker-compose.yml`，加入观测服务和 scrape/trace 所需环境变量。
- [ ] 更新 `.env.example`。
- [ ] Task 7 添加 alerts/dashboard 后一起提交。

## Task 7：Alerts 与 Grafana Dashboard

**文件：** `observability/alerts.yml`、Grafana provisioning、dashboard JSON

- [ ] 添加 Prometheus alert rules。
- [ ] 添加 Grafana provisioning。
- [ ] 添加 Grafana overview dashboard。
- [ ] 运行 config validation，确认 Task 6 和 Task 7 通过。
- [ ] 提交 Task 6 和 Task 7。

## Task 8：运维文档与完整验证

**文件：** `docs/observability.md`、`README.md`、验证脚本

- [ ] 编写可观测性运维文档，覆盖本地启动、访问地址、Metrics URL、关键指标、日志字段、排查流程和本地端口冲突。
- [ ] 运行 config validation。
- [ ] 运行 Go tests。
- [ ] 运行 Python tests。
- [ ] 运行 compose config check。
- [ ] 提交 Task 8。

## 自检清单

- GoFrame、Python Agent、MCP Server 都暴露 metrics。
- trace context 能跨 HTTP/gRPC/MCP 边界传播。
- `run_id` 与 `trace_id` 能共同定位业务链路。
- 日志使用结构化 JSON，并脱敏敏感字段。
- Grafana dashboard、Prometheus alert rules 和 Alertmanager 配置可本地启动。
- 观测组件不可用时，核心业务服务不应被阻塞。
