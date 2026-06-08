# KnowMate 观测运维手册

本文档面向本地开发、联调和故障排查。KnowMate 的本地观测栈包含 OpenTelemetry Collector、Jaeger、Prometheus、Grafana 和 Alertmanager，用于串联 GoFrame API、Python Agent、MCP Server、gRPC 调用、业务任务和 LLM 成本等信号。

业务服务不硬依赖 `otel-collector`。观测组件不可用时，核心服务启动和主业务流程不应被阻塞；此时优先恢复业务，再排查采集、链路和告警组件。

## 本地启动

在仓库根目录启动完整本地栈：

```powershell
docker compose up -d mysql embedding-mcp fetch-mcp milvus-mcp neo4j-mcp python-agent goframe-backend otel-collector jaeger prometheus alertmanager grafana
```

常用访问地址：

| 组件 | 地址 | 用途 |
| --- | --- | --- |
| GoFrame API | http://127.0.0.1:8080 | HTTP API 与业务入口 |
| Prometheus | http://127.0.0.1:9090 | 指标查询、告警规则评估 |
| Grafana | http://127.0.0.1:3000 | 仪表盘，默认本地账号通常为 `admin` / `admin` |
| Jaeger | http://127.0.0.1:16686 | 分布式 trace 查询 |
| Alertmanager | http://127.0.0.1:9093 | 告警接收、分组和静默 |

## Metrics URL

本地 Prometheus 会抓取以下 `/metrics` 端点。排查时也可以直接访问这些 URL：

| 服务 | Metrics URL |
| --- | --- |
| GoFrame Backend | http://127.0.0.1:8080/metrics |
| Python Agent | http://127.0.0.1:9101/metrics |
| Embedding MCP | http://127.0.0.1:7001/metrics |
| Fetch MCP | http://127.0.0.1:7002/metrics |
| Milvus MCP | http://127.0.0.1:7003/metrics |
| Neo4j MCP | http://127.0.0.1:7004/metrics |

Prometheus 配置位于 `observability/prometheus.yml`。如果直接访问 endpoint 有数据，但 Prometheus 没有数据，优先检查 scrape target 状态和容器网络。

## 关键指标

Grafana 总览仪表盘和 Prometheus 告警围绕以下指标域组织：

| 指标域 | 关注点 |
| --- | --- |
| task | 任务运行次数、成功率、失败率和部分完成状态 |
| crawler | 抓取文章数量、抓取状态、失败率和 partial 状态 |
| agent | Python Agent 工作流运行次数、状态和失败率 |
| grpc client/server | gRPC 客户端和服务端请求量、状态码、P95 延迟 |
| MCP tool | MCP 工具调用次数、状态、server/tool 维度延迟 |
| LLM tokens/cost | LLM token 消耗和成本累积，用于成本突增排查 |
| recommendation retention | 推荐结果保留率，关注筛选后 kept 占比 |
| posts generated | 生成帖子数量和失败率 |
| feedback received | 用户反馈接收与处理数量、失败率 |

告警规则文件位于 `observability/alerts.yml`。Grafana 仪表盘文件位于 `observability/grafana/dashboards/knowmate-overview.json`。

## 日志字段

排查链路时优先确认日志中是否带有以下字段：

| 字段 | 含义 |
| --- | --- |
| `trace_id` | 分布式 trace 标识，用于跳转 Jaeger |
| `span_id` | 当前 span 标识，用于定位 trace 内的具体步骤 |
| `run_id` | KnowMate 业务运行标识，用于串联一次任务的业务日志 |
| `service` | 产生日志的服务，例如 `goframe-backend` 或 `python-agent` |
| `level` | 日志级别，例如 `info`、`warn`、`error` |
| `message` | 人可读的事件描述 |

建议所有跨服务排查都从 `run_id` 开始，再用日志中的 `trace_id` 进入 Jaeger。

## 排查流程

1. 从 API 响应、任务记录、数据库或日志中拿到 `run_id`。
2. 按 `run_id` 搜索 GoFrame Backend、Python Agent 和 MCP Server 日志，确认失败发生在哪个服务、哪个步骤。
3. 从同一批日志中提取 `trace_id` 和必要的 `span_id`。
4. 打开 Jaeger `http://127.0.0.1:16686`，按 `trace_id` 查询完整调用链，查看失败 span、耗时异常和上下游状态。
5. 打开 Grafana `http://127.0.0.1:3000` 查看 KnowMate 总览仪表盘，确认同一时间段是否有错误率、延迟或成本异常。
6. 在 Prometheus `http://127.0.0.1:9090` 进一步查询原始指标，并检查 `Alerts` 页面是否已有触发中的告警。
7. 如告警已触发，打开 Alertmanager `http://127.0.0.1:9093` 查看告警分组、持续时间和静默状态。

典型定位顺序：

```text
run_id -> logs -> trace_id -> Jaeger -> Grafana/Prometheus
```

## 本地端口冲突

本地机器已有 MySQL、Grafana、Prometheus 或 OTLP Collector 时，Compose 默认端口可能冲突。优先通过环境变量调整 host 端口：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MYSQL_PORT` | `3306` | MySQL host 端口 |
| `GRAFANA_PORT` | `3000` | Grafana UI host 端口 |
| `PROMETHEUS_PORT` | `9090` | Prometheus UI host 端口 |
| `AGENT_METRICS_PORT` | `9101` | Python Agent metrics host 端口 |
| `OTEL_GRPC_PORT` | `4317` | OpenTelemetry Collector OTLP gRPC host 端口 |

PowerShell 示例：

```powershell
$env:MYSQL_PORT="3307"
$env:GRAFANA_PORT="3001"
$env:PROMETHEUS_PORT="9091"
$env:AGENT_METRICS_PORT="9111"
$env:OTEL_GRPC_PORT="4327"
docker compose up -d mysql python-agent goframe-backend otel-collector prometheus grafana
```

Jaeger 的 OTLP gRPC 容器端口是 `4317`，但本地 host 默认映射为 `4319`，用于避免和 `otel-collector` 的默认 host 端口 `4317` 冲突。业务服务默认向 `otel-collector:4317` 上报 trace，不需要直接依赖 Jaeger host 端口。

## 配置文件位置

| 文件 | 用途 |
| --- | --- |
| `observability/otel-collector.yml` | OpenTelemetry Collector pipeline |
| `observability/prometheus.yml` | Prometheus scrape、rule 和 Alertmanager 配置 |
| `observability/alerts.yml` | KnowMate 告警规则 |
| `observability/alertmanager.yml` | Alertmanager 路由与接收配置 |
| `observability/grafana/dashboards/knowmate-overview.json` | KnowMate Grafana 总览仪表盘 |
| `observability/grafana/provisioning/datasources/prometheus.yml` | Grafana Prometheus 数据源 provisioning |
| `observability/grafana/provisioning/dashboards/dashboards.yml` | Grafana dashboard provisioning |

## 验证

修改观测配置后运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_observability_config.ps1
```

该脚本会检查 Compose 服务、观测配置文件和 Grafana dashboard 标题是否符合本地栈要求。
