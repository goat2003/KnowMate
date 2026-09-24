# 已知限制列表

## 部署与运行

- Kubernetes manifests 是生产候选基线，不包含 Ingress、TLS、HPA、PDB、NetworkPolicy、外部 Secret Controller 和完整资源配额。
- Kubernetes 中 Milvus 与 Neo4j 推荐使用托管服务或官方 Chart；本仓库提供的是 MCP 应用侧 manifests 和运维接入说明。
- MySQL Kubernetes manifest 是单副本候选配置，生产高可用建议使用托管 MySQL 或 Operator。
- 2026-09-19 已完成隔离本机环境的容器启动、真实抓取/数据库、访问控制和备份恢复验收，见 `docs/LOCAL_SERVER_WORK_REPORT.md`。文本生成和 embedding 使用模拟结果，真实模型 API 验收仍待凭据；不得外推为公网/Kubernetes 验收。

## 数据与一致性

- Migration runner 已维护文件名/checksum/执行时间 ledger；重复文件跳过、变更文件拒绝。MySQL DDL 失败不保证事务回滚，尚无自动 schema 回滚。
- GoFrame Harness 多副本下仍主要依赖数据库任务状态降低重复执行风险，后续需要更强的分布式锁或队列。
- Markdown 输出在 Kubernetes 示例中使用 `emptyDir`，适合生产候选验收；正式生产应改为对象存储或持久卷。

## 产品与安全

- Web Admin 当前不是完整 RBAC 后台，生产应在反向代理或后续登录模块中注入/管理 API token。
- 隔离本机环境的真实 Milvus/Neo4j 已验收；真实聊天/embedding 模型尚未接入。常规单元测试仍使用 fixture 和 memory provider。
- LLM 真实输出质量不由 fixture 测试完全覆盖，需要独立评测集和人工抽样。
