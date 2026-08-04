# KnowMate 生产候选发布检查清单

> 原文镜像：`RELEASE_CHECKLIST.md`
>
> 原文件已以中文为主；本镜像保留命令、路径、代码块和协议字段原样。


本文用于发布 `knowledge-post-agent` 生产候选版本。默认发布目标为 Docker Compose 或 Kubernetes，服务包含 GoFrame Backend、Python Agent、四个 MCP Server、Web Admin、MySQL、Milvus、Neo4j 与观测组件。

## 发布前冻结

- [ ] 确认当前分支没有未解释的业务改动：`git status --short`
- [ ] 确认 `.env`、真实密钥、数据库 dump、私钥没有进入提交：`python scripts/check_secrets.py --all`
- [ ] 确认版本号、镜像 tag、发布窗口和回滚负责人已经记录。
- [ ] 确认生产 secret 已在目标环境创建：`MYSQL_PASSWORD`、`GOFRAME_API_TOKEN`、`AGENT_GRPC_AUTH_TOKEN`、`OPENAI_API_KEY`、`NEO4J_PASSWORD`、`MINIO_ROOT_PASSWORD`、`GRAFANA_ADMIN_PASSWORD`。
- [ ] 确认生产抓取源文件已经替换或批准使用默认英文公开示例：`configs/crawler/prod.sources.example.yaml` 或受控 `configs/crawler/prod.sources.yaml`。
- [ ] 确认生产 enabled 源不包含 `mock://sample`，并已复核授权、服务条款、robots.txt、请求频率、缓存策略和失败降级。

## 构建与静态验收

- [ ] 执行最终验收入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\final_acceptance.ps1 -SkipDockerBuild
```

- [ ] 有 Docker 可用时构建全部镜像：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\final_acceptance.ps1
```

- [ ] 校验生产 Compose：

```powershell
docker compose --env-file .\configs\env\prod.env -f .\docker-compose.prod.yml config
```

- [ ] 确认渲染后的 `goframe-backend` 包含 `CONFIG_PATH=/app/goframe-backend/manifest/config/prod.sources.yaml`，并挂载 `${CRAWLER_CONFIG_PATH:-./configs/crawler/prod.sources.example.yaml}`。
- [ ] Kubernetes 发布前确认 `deploy/kubernetes/app-config.yaml` 中 `knowmate-crawler-config` 已替换为目标环境源，`deploy/kubernetes/goframe-backend.yaml` 已挂载 `prod.sources.yaml`。
- [ ] 校验 Kubernetes manifests：

```powershell
kubectl apply --dry-run=client --validate=false -f .\deploy\kubernetes
```

## 数据库 migration

- [ ] 执行静态 migration 校验：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_migrations.ps1
```

- [ ] 生产发布前备份 MySQL，记录备份文件名与校验值。
- [ ] Compose 发布时确认 `migration-runner` 成功退出：

```powershell
docker compose -f .\docker-compose.prod.yml ps migration-runner
docker compose -f .\docker-compose.prod.yml logs migration-runner
```

- [ ] Kubernetes 发布时先运行 Job 并确认成功：

```powershell
kubectl apply -f .\deploy\kubernetes\migration-job.yaml
kubectl -n knowmate wait --for=condition=complete job/migration-runner --timeout=180s
```

## 最终验收

- [ ] 完整启动所有服务。
- [ ] 抓取生产源或批准的 fixture：生产 Compose/Kubernetes 默认不启用 `mock://sample`，真实源在生产窗口抽样并记录每个 source 的 `crawl_source_runs` 状态。
- [ ] 完成筛选、总结、改写和检查：检查 `POST /runs/articles` 返回 `completed` 或明确 `partially_completed`。
- [ ] 保存文章与推文：检查 MySQL `articles`、`posts`。
- [ ] 生成 Markdown：检查 `shared/outputs` 或容器卷 `markdown-outputs`。
- [ ] 提交反馈并更新用户画像：调用 `POST /feedback` 后检查 `user_profile_snapshot.version` 增长。
- [ ] 验证 Milvus 与 Neo4j 数据：检查 MCP health，必要时运行 `scripts/init_memory_services.py`。
- [ ] 验证失败重试和任务恢复：检查 `/runs/{run_id}/retry` 与服务重启后的 `pending` 恢复。
- [ ] 验证 MCP 权限拒绝：运行 `python-agent/tests/test_mcp_policy.py` 或查看 `MCP_PERMISSION_DENIED` 日志。
- [ ] 验证管理后台主要流程：运行 `npm run playwright` 或人工检查触发抓取、任务详情、推文详情、反馈、MCP 日志页。

## 发布命令

Compose:

```powershell
docker compose --env-file .\configs\env\prod.env -f .\docker-compose.prod.yml up -d --build
docker compose -f .\docker-compose.prod.yml ps
```

Kubernetes:

```powershell
kubectl apply -f .\deploy\kubernetes\namespace.yaml
kubectl apply -f .\deploy\kubernetes\app-config.yaml
kubectl apply -f .\deploy\kubernetes\secrets.yaml
kubectl apply -f .\deploy\kubernetes\mysql.yaml
kubectl apply -f .\deploy\kubernetes\migration-job.yaml
kubectl -n knowmate wait --for=condition=complete job/migration-runner --timeout=180s
kubectl apply -f .\deploy\kubernetes\mcp-servers.yaml
kubectl apply -f .\deploy\kubernetes\python-agent.yaml
kubectl apply -f .\deploy\kubernetes\goframe-backend.yaml
kubectl apply -f .\deploy\kubernetes\web-admin.yaml
kubectl apply -f .\deploy\kubernetes\observability.yaml
```

## 回滚检查

- [ ] 保留上一版本镜像 tag。
- [ ] 数据库 migration 已确认向后兼容；若需结构回滚，先恢复备份到新实例并切流。
- [ ] Compose 回滚：改回上一版 `.env`/镜像 tag 后 `docker compose up -d`。
- [ ] Kubernetes 回滚：`kubectl -n knowmate rollout undo deployment/goframe-backend deployment/python-agent deployment/web-admin`。

## 已知限制

- Kubernetes manifests 是生产候选基础版，不包含 Ingress、证书、NetworkPolicy、HPA 和外部 secret controller。
- K8s 中 Milvus 与 Neo4j 推荐使用托管服务或官方 Helm Chart，本仓库只提供 MCP 应用侧 manifests。
- MySQL manifest 是单副本候选配置；生产高可用建议使用托管 MySQL 或 Operator。
- Web Admin 依赖 GoFrame API token，当前前端只支持运行时传入 token 或反向代理层注入，未内置用户登录。
- 真实 OpenAI、Milvus、Neo4j 验收需要外部凭据和网络；默认 CI/本地验收仍以 fixture 和 memory provider 为主。

## 下一版本规划

- 引入 Helm Chart，并支持环境 values、Ingress、TLS、HPA、PDB、NetworkPolicy。
- 增加 migration 版本表和失败自动锁定，支持审计每次 schema 变更。
- Web Admin 增加 RBAC 登录、API token 管理和运行时配置页。
- 补齐生产级 Milvus/Neo4j Operator 集成文档与自动 smoke。
- 将最终验收报告自动输出为 JSON/Markdown 工件并接入 CI。
