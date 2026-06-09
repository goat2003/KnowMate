# 已知限制列表

## 部署与运行

- Kubernetes manifests 是生产候选基线，不包含 Ingress、TLS、HPA、PDB、NetworkPolicy、外部 Secret Controller 和完整资源配额。
- Kubernetes 中 Milvus 与 Neo4j 推荐使用托管服务或官方 Chart；本仓库提供的是 MCP 应用侧 manifests 和运维接入说明。
- MySQL Kubernetes manifest 是单副本候选配置，生产高可用建议使用托管 MySQL 或 Operator。
- 本机 Docker 构建与 E2E smoke 在当前环境受 `image-mirror.r2.daocloud.vip` 镜像拉取 EOF 阻塞；业务链路未能在本机容器中完整启动验收，需要切换 Docker 镜像源、预拉 base images 或在 CI/生产网络复跑。

## 数据与一致性

- Migration 通过一次性 runner 自动执行，但当前未维护独立 schema version 表；幂等性依赖 migration 自身实现和 `scripts/verify_migrations.ps1`。
- GoFrame Harness 多副本下仍主要依赖数据库任务状态降低重复执行风险，后续需要更强的分布式锁或队列。
- Markdown 输出在 Kubernetes 示例中使用 `emptyDir`，适合生产候选验收；正式生产应改为对象存储或持久卷。

## 产品与安全

- Web Admin 当前不是完整 RBAC 后台，生产应在反向代理或后续登录模块中注入/管理 API token。
- 真实 OpenAI、Milvus、Neo4j 验收需要外部凭据和网络；默认本地测试仍以 fixture 与 memory provider 为主。
- LLM 真实输出质量不由 fixture 测试完全覆盖，需要独立评测集和人工抽样。
