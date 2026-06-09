# 下一版本规划

## P0: 生产发布硬化

- 增加 Helm Chart，支持 `values-dev.yaml`、`values-test.yaml`、`values-prod.yaml`。
- 引入 Ingress/TLS、NetworkPolicy、PodDisruptionBudget、HPA 和资源 requests/limits。
- 增加 schema version 表，记录 migration 文件名、checksum、执行时间、执行人和结果。
- 将 Markdown 输出迁移到对象存储，并在 GoFrame 中抽象输出适配器。

## P1: 可靠性与任务系统

- 引入分布式锁或队列，保证多副本 GoFrame 下任务领取和重试严格幂等。
- 增加补偿任务后台 worker，自动重放 Milvus/Neo4j 写入失败。
- 生成最终验收 JSON/Markdown 报告，接入 CI artifact。
- 增加真实 Milvus/Neo4j/OpenAI 的可选 nightly smoke。

## P2: 管理后台与安全

- Web Admin 增加登录、角色权限、API token 管理和审计日志。
- 增加管理后台运行时配置页，支持查看 crawler sources、MCP provider 和 LLM provider。
- 增加用户画像 diff 可视化、回滚确认流和补偿任务管理页。
- 增加 Web Admin 容器运行时 API base URL 配置，不再依赖固定 Nginx upstream。

## P3: 推荐与内容质量

- 建立推荐评测集，跟踪 Precision@K、Recall@K、NDCG、重复率和多样性趋势。
- 增加真实网页抓取合规策略配置，包括 robots、User-Agent、站点限速和失败白名单。
- 增加 LLM 输出质量抽样与人工反馈闭环。
