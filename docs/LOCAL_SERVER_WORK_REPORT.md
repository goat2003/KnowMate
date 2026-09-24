# 本机服务器准备工作报告

日期：2026-09-19。项目：`D:\projects\KnowMate\knowledge-post-agent`。

## 交付结论

已完成本机单管理员服务器的部署实现和不依赖真实模型的验收。正式环境的独立数据存储、凭据、TLS、镜像、启动检查和备份已准备；填写真实聊天/embedding API 后，执行一条 `start` 命令即可进行真实供应商探测并启动业务服务，无需另行开发部署代码。

**真实模型尚未配置，因此不能宣称真实模型业务已验收。** 当前可用的 https://localhost:9443 是演练环境：真实网页、MySQL、Milvus、Neo4j，模拟文本生成和 embedding。正式入口 https://localhost:8443 会在 API 探测和启动成功后启用。本次范围不包含公网/多租户/高可用部署。

## 已完成的实现

| 工作 | 实际结果 |
| --- | --- |
| 隔离部署 | 新建 `knowmate-rehearsal`、`knowmate-production`，独立数据卷与密钥；原开发栈及其他项目未重建/清库 |
| 登录与网络 | HTTPS、随机管理员密码、网关注入 API token、拒绝匿名请求和跨站写入；新栈只对本机发布网关 |
| 密钥保护 | `.local-server` 限制 Windows ACL，Git/Docker context 排除；支持挂载 secret 文件，报告不含凭据 |
| 生产防误用 | 禁止 mock 和静默模拟回退；真实模型 JSON/embedding 维度预检；容器启动再次验证供应商 |
| 就绪检查 | `/ready` 验证数据库和 Agent，依赖失败返回 503，检查超时限制 2 秒 |
| 数据迁移 | 文件名/checksum/执行时间 ledger；重复跳过、已执行文件变更拒绝 |
| 监控与告警 | Prometheus、Alertmanager、Grafana、OTel、Jaeger、本地告警记录；服务离线、备份过期、磁盘不足指标 |
| 备份与恢复 | AES-256-GCM 冷备、每卷 SHA-256、独立恢复、拒绝覆盖已有目标；03:00 Windows 计划任务 |
| 配置更新 | bind mount 与 secret 内容摘要触发对应服务重建；初始化中断后可继续 |
| 依赖修复 | Go 1.26.8、gRPC 1.83.2 及相关模块；Python 漏洞版本约束；前端 lockfile/esbuild 更新 |
| 业务缺陷修复 | PyMilvus 返回的 protobuf 容器先转 JSON 基本类型，避免“写入成功但响应失败”的重复重试；向量写入保留用户归属 |

## 实测与证据

所有相对路径均以项目根目录为基准。私有验收 JSON 含本机业务数据，不应直接公开。

| 验收 | 结果 | 证据 |
| --- | --- | --- |
| 本机抓取及落库 | Hugging Face 官方博客，2 篇文章、2 篇演练推文、Markdown 输出；重复抓取新增 0 篇 | `.local-server/rehearsal/business-report.json` |
| 一条测试反馈 | `local-acceptance`，SQL 中 1 条反馈、画像版本 1 | 同上 |
| 反馈记忆修复后重放 | 复用原 run ID；embedding、Milvus upsert、Neo4j update 均成功，未新增 SQL 反馈 | `.local-server/rehearsal/memory-replay-report.json` |
| 鉴权/就绪/观测 | 匿名 401、外站写入 403；DB ok、Agent SERVING；9 个监控目标 up | `.local-server/rehearsal/verification.json` |
| 故障恢复 | 分别停 Agent/MySQL，ready 为 503，恢复后通过；停 fetch 触发真实 ServiceDown 并送达告警日志 | `.local-server/rehearsal/drill-report.json`、`events/alerts.jsonl` |
| 迁移 | 重放跳过；容器临时副本修改 checksum 后拒绝执行，未改原迁移文件 | `.local-server/rehearsal/migration-report.json` |
| 中断任务 | 标记为测试的运行中任务，经重启恢复为 pending，手动重试 completed | `.local-server/rehearsal/recovery-report.json` |
| 浏览器 | 真实 HTTPS 登录、概览/MCP 日志/推文详情读取数据；控制台 0 errors/0 warnings | `output/playwright/` 下 DOM 快照与截图 |
| 基础质量门禁 | secret/proto/migration、gofmt/vet/Go tests、ruff/mypy、Python/benchmark 通过；Go 覆盖率 54.3%、Python 82.21% | `artifacts/quality-final.log` |
| 最终 Python 回归 | 131 passed、3 skipped；跳过项不计通过 | `artifacts/tests-final.log` |
| 升级依赖的容器内测试 | Agent 83 passed；MCP 44 passed、3 skipped；后续业务修复另有 21 项针对性回归及真实 MCP 重放 | `artifacts/agent-image-tests.log`、`mcp-image-tests.log` |
| 前端 | 9 项测试通过，生产构建通过，最终镜像已构建 | `artifacts/web-build-final.log` |
| 漏洞扫描 | Go 包/模块扫描、两个 Python 运行镜像的已安装包清单、npm audit 均未发现已知漏洞 | `artifacts/go-vuln-final.log`、`python-agent-runtime-audit.json`、`mcp-servers-runtime-audit.json`、`web-audit.json` |
| 未配置 API 防误启动 | production preflight 返回非零，提示配置聊天与 embedding API；未调用真实模型 | `scripts/local_server.py preflight --stage production` |

Python requirements 在线解析扫描曾因网络失败；最终采用**实际构建镜像的已安装版本清单**逐镜像扫描并通过。该结论覆盖应用依赖，不等于扫描过全部基础镜像 OS 包，也不保证未来无新漏洞。

最初测试反馈的历史 MCP 日志仍保留一次序列化失败及补偿任务，未篡改为成功。修复后沿用同一反馈 ID 直接走认证 gRPC 重放，三个记忆调用成功。因原 upsert 已落盘，不重新提交反馈、不增加 SQL 画像版本。历史失败应结合修复后的重放报告阅读。

## 备份恢复结果

演练备份：`.local-server/backups/rehearsal-20260919T042218Z.kmbackup`，10 个卷，总用时 139.92 秒。SHA-256：

```text
7150b0e6d9c71970ebb345d75284e8bbbe350cfb458a60cb01a78d72ca6db0f9
```

恢复到独立 `knowmate-restore` 用时 32.01 秒，五个基础设施服务健康，恢复后对照：

| 数据 | 源/恢复结果 |
| --- | --- |
| articles / posts / feedback_logs | 2 / 2 / 1，完全一致 |
| task_runs / task_steps / user_profile_snapshot | 3 / 19 / 1，完全一致 |
| mcp_call_logs / schema_migrations | 9 / 3，完全一致 |
| Neo4j | 5 节点、3 关系，一致 |
| Milvus collection stats | row_count 3，一致；这是存储统计，包含 upsert 版本，不应解读为 3 条独立用户记忆 |

证据：`.local-server/restore/restore-report.json`、`data-verification.json`。这是备份时点的比对；随后进行了反馈修复重放和任务恢复测试，演练源数据继续变化。恢复实例已停止，数据卷保留。

正式环境计划任务也已实际手动触发成功，`LastTaskResult=0`，生成 `.local-server/backups/production-20260919T044003Z.kmbackup`：6 个卷、26.8 秒。下次计划运行：2026-09-20 03:00（Asia/Shanghai）。这是正式环境尚未投入业务时的基础设施快照。

## 交付状态与启用方法

1. 打开 `.local-server/production/model.env`，填写真实聊天与 embedding 服务配置。
2. 执行 `python -B scripts/local_server.py start --stage production`。
3. 使用 `.local-server/production/admin-credentials.txt` 中的凭据访问 https://localhost:8443，触发一次真实文章任务并审核结果。

详细命令、备份密钥保管、证书、监控入口、升级方式见 [操作手册](LOCAL_SERVER.md)。四个本地应用镜像身份保存在 `artifacts/local-image-manifest.json`。

本次为直接修改工作区并部署本机，没有替用户提交 Git 或发布到远程。保留了原有 `docs/zh-CN/ARCHITECTURE.md` 改动和 `go.mod` 的依赖分类调整；在其基础上加入必要补丁。清理了本次测试产生的已跟踪 pyc 改动与临时测试输出。为构建临时使用的代理转发进程已停止，没有改写 Docker 全局代理设置；未来重新拉镜像仍要求有效的 Docker 网络配置。

## 仍需真实凭据确认的事项

- 模型账号可用、容器能访问供应商、额度/限流、结构化输出兼容性、向量维度匹配及生成质量。启动命令会验证连接和基础格式；内容质量仍需真实任务抽样。
- 本机保持开机、登录并运行 Docker Desktop；当前配置不承诺断电、系统重启前登录阶段或整机故障时继续服务。
- 中断任务恢复为待重试，需要管理员操作；跨系统写失败会留补偿记录，尚无自动补偿后台 worker。
- 本地备份与本地告警不等于异地容灾和外部通知；未配置公网域名、多用户角色权限和高可用集群。

这些边界不会被模拟模型验收掩盖。对“本机单管理员、填写有效模型配置后启动工作”的范围，部署与运维准备已交付；真实供应商验收留待 API 配置后执行。
