# KnowMate 运维手册

## 服务清单

- `goframe-backend`: HTTP API，端口 `8080`，健康检查 `/health`，指标 `/metrics`。
- `python-agent`: gRPC Agent Service，端口 `50051`，指标 `9101`。
- `embedding-mcp`: embedding MCP，端口 `7001`，健康检查 `/health`。
- `fetch-mcp`: 抓取/正文提取 MCP，端口 `7002`，健康检查 `/health`。
- `milvus-mcp`: Milvus 记忆向量 MCP，端口 `7003`，健康检查 `/health`。
- `neo4j-mcp`: Neo4j 用户兴趣图 MCP，端口 `7004`，健康检查 `/health`。
- `web-admin`: 管理后台，端口 `8080` 或 Compose 外部 `WEB_ADMIN_PORT`。
- `mysql`: 主业务库。
- `milvus`、`neo4j`: 生产记忆服务，Kubernetes 推荐托管或官方 Chart。

## 配置分层

- 开发：`configs/env/dev.env`，默认 mock LLM/MCP 与 memory provider。
- 测试：`configs/env/test.env`，固定 token，较小抓取规模。
- 生产：复制 `configs/env/prod.env.example` 为受控环境变量文件或平台 Secret。

不要提交 `.env` 或真实 secret。Kubernetes 使用 `deploy/kubernetes/secrets.example.yaml` 复制为 `secrets.yaml` 后替换真实值。

## 生产抓取源

生产 Compose 和 Kubernetes 不再依赖内置 `mock://sample`。GoFrame 启动时读取 `CONFIG_PATH`：

- Compose: `docker-compose.prod.yml` 将 `${CRAWLER_CONFIG_PATH:-./configs/crawler/prod.sources.example.yaml}` 只读挂载为 `/app/goframe-backend/manifest/config/prod.sources.yaml`。
- Kubernetes: `deploy/kubernetes/app-config.yaml` 提供 `knowmate-crawler-config`，`deploy/kubernetes/goframe-backend.yaml` 使用 `subPath` 挂载同名文件。

上线前替换真实源的推荐流程：

```powershell
Copy-Item .\configs\crawler\prod.sources.example.yaml .\configs\crawler\prod.sources.yaml
notepad .\configs\crawler\prod.sources.yaml
```

然后在受控 `configs/env/prod.env` 中设置：

```env
CRAWLER_CONFIG_PATH=./configs/crawler/prod.sources.yaml
```

默认公开示例源只使用英文来源：arXiv `cs.AI/cs.LG/cs.CL/cs.CV`、OpenAI/LangChain/MCP/Milvus/Neo4j GitHub Releases、OpenAI News、LangChain Blog、Google Research、Hugging Face Blog。`huggingface_papers` 和 `mock` 在生产示例中均为 disabled；Hugging Face Daily Papers 当前只有官方 HTML 页面已确认公开，`/papers/rss` 在本机验证返回 401，启用前必须确认官方 RSS/API 权限或扩展 adapter。

所有真实源都必须在发布窗口前复核授权、服务条款、robots.txt、请求频率、缓存策略和失败降级。公开 feed 也不等于可无限抓取；必要时用 `CRAWLER_PER_HOST_INTERVAL_MILLISECONDS`、`CRAWLER_SOURCE_MAX_ITEMS`、`CRAWLER_RUN_MAX_ARTICLES` 收紧频率。

## 健康检查与优雅关闭

- GoFrame: `/health` 检查 MySQL 与 Python Agent，容器内 `HEALTHCHECK` 使用 HTTP 探测；进程启用 GoFrame graceful shutdown。
- Python Agent: gRPC `HealthCheck`，接收 `SIGINT/SIGTERM` 后停止接收新请求，等待 gRPC grace，然后关闭 workflow/MCP client。
- MCP Server: `/health` 返回 provider ready 状态；生产依赖不可用时返回 `503`，进程保持存活便于恢复。
- Web Admin: `/healthz` 静态健康检查。

Kubernetes manifests 均配置 `runAsNonRoot`、`allowPrivilegeEscalation: false`、readiness/liveness probe 和滚动更新策略。

## 数据库 migration 自动执行策略

策略：migration 不由每个应用副本在启动时抢跑，而是由一次性 `migration-runner` 自动执行。

Compose:

```powershell
docker compose --env-file .\configs\env\prod.env -f .\docker-compose.prod.yml up migration-runner
docker compose --env-file .\configs\env\prod.env -f .\docker-compose.prod.yml up -d
```

Kubernetes:

```powershell
kubectl apply -f .\deploy\kubernetes\migration-job.yaml
kubectl -n knowmate wait --for=condition=complete job/migration-runner --timeout=180s
```

Runner 会先执行 `shared/sql/init.sql`，再按文件名顺序执行 `shared/sql/migrations/*.sql`。迁移脚本必须保持幂等，新增脚本后运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_migrations.ps1
```

## 备份

MySQL 逻辑备份：

```powershell
$ts = Get-Date -Format "yyyyMMddHHmmss"
docker compose -f .\docker-compose.prod.yml exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction --routines --triggers knowledge_post_agent' > "artifacts\backup\mysql-$ts.sql"
```

Markdown 输出备份：

```powershell
Compress-Archive -Path .\shared\outputs\* -DestinationPath "artifacts\backup\markdown-$ts.zip"
```

Neo4j 备份建议使用托管服务快照或 `neo4j-admin database dump`；Milvus 备份建议使用存储层快照或官方备份工具。Compose 候选环境至少备份 `neo4j-data`、`milvus-data`、`milvus-minio-data` 卷。

## 恢复

MySQL 恢复到新库或维护窗口内恢复：

```powershell
Get-Content .\artifacts\backup\mysql-YYYYMMDDHHMMSS.sql | docker compose -f .\docker-compose.prod.yml exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot knowledge_post_agent'
```

恢复后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_migrations.ps1 -RequireDatabase
python .\scripts\init_memory_services.py
```

如果应用已经写入新 schema，优先恢复到新实例并切换连接，不建议直接在旧实例上做破坏性回滚。

## 日志

- GoFrame 使用结构化 JSON 日志，重点字段：`service`、`level`、`message`、`run_id`、`task_type`。
- Python Agent 记录 gRPC、LLM、MCP 调用状态，MCP 请求/响应会脱敏。
- MCP Server 记录 provider、tool、status、latency。
- GoFrame 持久化 `run_logs`、`task_runs`、`task_steps`、`mcp_call_logs`，用于任务恢复和审计。

常用排障：

```powershell
docker compose -f .\docker-compose.prod.yml logs --tail=200 goframe-backend
docker compose -f .\docker-compose.prod.yml logs --tail=200 python-agent
docker compose -f .\docker-compose.prod.yml logs --tail=200 milvus-mcp neo4j-mcp
kubectl -n knowmate logs deploy/goframe-backend --tail=200
```

## 监控

本地/Compose 使用 `observability/prometheus.yml`、`observability/alerts.yml`、Grafana dashboard。Kubernetes manifests 提供最小 Prometheus/Grafana 部署，可按平台替换为托管 Prometheus。

关键指标：

- GoFrame: HTTP 请求量、延迟、状态码、任务运行数。
- Python Agent: gRPC 请求量、延迟、失败率、Agent workflow 耗时。
- MCP: tool 调用量、失败率、fallback 次数、provider latency。
- MySQL: 连接可用性、慢查询、磁盘空间。
- Milvus/Neo4j: health、查询延迟、写入失败。

## 告警

建议生产至少启用：

- 任一核心服务 readiness 连续 5 分钟失败。
- `/runs/articles` 或 `ProcessArticles` 失败率 10 分钟内超过 5%。
- MCP `denied` 突增或高风险工具被拒绝。
- MCP fallback 次数持续上升。
- MySQL 磁盘空间低于 20%。
- migration Job 失败。
- 任务长时间卡在 `running` 或 `pending`。

仓库已有 `observability/alerts.yml` 可作为 Prometheus 规则起点。

## 发布

1. 构建并推送四类镜像：`goframe-backend`、`python-agent`、`mcp-servers`、`web-admin`。
2. 执行 MySQL/Milvus/Neo4j 备份。
3. 执行 migration-runner。
4. 滚动发布 MCP、Python Agent、GoFrame、Web Admin。
5. 执行 `RELEASE_CHECKLIST.md` 的最终验收。

## 回滚

应用回滚优先使用镜像回滚：

```powershell
kubectl -n knowmate rollout undo deployment/goframe-backend
kubectl -n knowmate rollout undo deployment/python-agent
kubectl -n knowmate rollout undo deployment/web-admin
```

数据回滚必须先评估 migration 是否向后兼容。若已经写入新 schema 或新数据语义，建议恢复备份到新数据库实例，然后切换 `MYSQL_DSN` 并重新发布，不在原库上直接删除列或删表。

## 验收脚本

默认最终验收：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\final_acceptance.ps1
```

只做快速静态验收：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\final_acceptance.ps1 -SkipDockerBuild -SkipWeb
```

运行完整 fixture E2E：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\final_acceptance.ps1 -RunE2E
```

真实 Milvus 与 Neo4j 验收：

```powershell
$env:MINIO_ROOT_USER="..."
$env:MINIO_ROOT_PASSWORD="..."
$env:NEO4J_PASSWORD="..."
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\final_acceptance.ps1 -RunE2E -RealMemoryServices
```
