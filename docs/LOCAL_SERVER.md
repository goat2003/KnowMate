# 本机服务器操作手册

适用范围：Windows + Docker Desktop、本机访问、单管理员、单实例。所有命令在项目根目录执行。此部署与原来的 `knowledge-post-agent` 开发栈、其他项目的容器和数据卷隔离。

## 当前入口

| 环境 | 地址 | 状态与用途 |
| --- | --- | --- |
| rehearsal | https://localhost:9443 | 已运行；真实抓取和数据库，模拟文本生成与 embedding，仅用于验收 |
| production | https://localhost:8443 | 基础设施已准备；填入真实模型配置后启动业务服务 |
| restore | 无对外端口 | 独立备份恢复验证实例；验收后已停止，保留数据卷 |

登录账号为 `admin`。分别打开 `.local-server/rehearsal/admin-credentials.txt` 或 `.local-server/production/admin-credentials.txt` 获取对应密码。不要把这些文件发到聊天、提交到 Git 或放进公开报告。浏览器使用 HTTPS Basic 登录；API token 由网关注入，无需在前端填写。

新部署只发布 `127.0.0.1` 上的网关端口。原开发栈仍保留原有端口发布方式；新部署的网络限制不会自动改写旧栈。

## 填入 API 后启用正式工作

1. 编辑 `.local-server/production/model.env`。填写聊天模型的 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`，以及 embedding 的 `EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`、`EMBEDDING_DIMENSION`。URL 必须是 HTTPS 的 OpenAI 兼容 API base，例如以 `/v1` 结尾，不能包含用户名或密码。
2. 如果两个模型来自同一账号，`EMBEDDING_API_KEY` 留空会复用 `OPENAI_API_KEY`。只提供聊天功能的供应商不能替代 embedding 服务；这时要单独填写 embedding 凭据。默认 embedding 为 `text-embedding-3-large`、3072 维；已有数据后不要直接改变维度。
3. 执行：

```powershell
python -B scripts/local_server.py start --stage production
```

该命令实际调用聊天和 embedding API，验证 JSON 输出和向量维度，然后启动迁移、MCP、Agent、后台和观测组件并验收访问控制。Agent 和 embedding 服务还会从容器网络再次探测供应商。探测会产生少量 API 用量。配置为空、供应商不兼容、容器无法联网或探测失败都会阻止正常启用；生产配置禁止静默切回 mock。

4. 打开 https://localhost:8443，点击“手动触发抓取”，在任务记录检查结果，在推文详情检查模型真实输出，再提交业务反馈。真实输出质量、账号额度、限流及供应商可用性必须在这一步确认。

本次没有配置或调用真实模型 API。上述步骤完成前，不能把 rehearsal 的文章内容当作真实模型成果。

## 常用运维

```powershell
# 检查当前环境
python -B scripts/local_server.py check --stage rehearsal
python -B scripts/local_server.py check --stage production

# 只启动正式环境数据库基础设施，不调用模型
python -B scripts/local_server.py prepare --stage production

# 停止演练服务以释放内存；保留所有数据卷
python -B scripts/local_server.py stop --stage rehearsal

# 查看正式服务状态及日志（不要对外分享包含业务内容的原始日志）
docker compose -p knowmate-production -f .local-server/production/compose.yaml ps
docker compose -p knowmate-production -f .local-server/production/compose.yaml logs --tail 100 goframe-backend python-agent
```

抓取源在各环境的 `sources.yaml`，默认使用 Hugging Face 官方博客，每次最多 2 篇，保守限制流量。修改源、API 或观测配置后重新执行对应环境的 `start`；脚本按文件摘要重建需要重载的容器。`init` 支持中断后再次执行，不会重新生成已有密钥。

`/api/ready` 检查 MySQL 与 Agent，可用时返回 200，失败时在约 2 秒内返回 503；`/api/health` 用于诊断。除 `/wechat/callback` 外，网关路径都要求登录；微信回调由后端验证签名和加密消息，默认关闭。观测入口为 `/monitor/`、`/alerts/`、`/grafana/`、`/tracing/`。Grafana 自身的管理员密码位于相应环境 `secrets.json` 的 `GRAFANA_ADMIN_PASSWORD` 字段。

本机 TLS 证书有效期一年，当前两张证书已加入当前 Windows 用户信任区。迁移到新账户/机器时需重新建立信任；续期须更换证书并重启网关。不能直接将本机证书用于公网域名。

## 备份与恢复

已安装 Windows 计划任务 `KnowMate-Local-Backup`，每天 03:00 运行正式环境加密冷备。任务要求当前用户已登录且 Docker Desktop 可用；错过时间会在可运行时补执行。**冷备会短暂停止该环境全部服务**，完成快照后恢复原来运行的服务。带业务数据的本次演练总用时约 140 秒，实际维护时间随数据量增长。

```powershell
python -B scripts/local_backup.py backup --stage production

# 新机器或尚无 knowmate-restore 实例时才运行；绝不覆盖已有目标
python -B scripts/local_backup.py restore --archive .local-server/backups/production-YYYYMMDDTHHMMSSZ.kmbackup
```

备份包含命名数据卷、Markdown 输出和受保护的配置，使用 AES-256-GCM 加密，每个卷有 SHA-256 校验。恢复会先验证认证标签和校验和，再创建独立 `knowmate-restore` 环境，不会覆盖 production。现有恢复演练目标会使再次恢复明确报错；不要为复跑而删除正式环境的数据卷。

`.local-server/backup.key` 是解密必需品，不包含在备份中。应将它与 `.kmbackup` 文件分别保存到受控的异机介质。只有本地副本无法抵御整机/磁盘丢失。本次未配置异地存储和自动清理；定期检查备份目录容量。

告警本地落盘到 `.local-server/<stage>/events/alerts.jsonl`，包含服务下线、备份超过 36 小时、磁盘空闲不足 10%。没有配置邮件/聊天外发；整机离线时本机监控也会停止。

## 升级和边界

升级前先备份，再运行 `python -B scripts/local_server.py build`，最后执行 `start`。当前网络下也可使用 `build --cached-runtime`，它需要本机 Go 模块缓存和已有后端运行镜像；本次已用修复后的 Go 1.26.8 编译并验证。镜像不是备份的一部分，长期归档还应保留匹配的镜像版本。

数据库迁移使用 `schema_migrations` 保存文件名、SHA-256、执行时间；已执行文件不能改写，应追加新迁移。MySQL DDL 不保证事务回滚，失败时先检查状态，不能把 checksum 表当作自动回滚机制。

容器设置了自动重启策略，但 Windows 需保持开机、避免休眠，并启动 Docker Desktop。中断任务在后端重启后恢复为 `pending`，由后台手动重试；目前没有无人值守的分布式任务重放队列。此交付不包含公网访问、多租户 RBAC、多副本高可用、外部告警和异地容灾。

验收记录见 [本机工作报告](LOCAL_SERVER_WORK_REPORT.md)。不要在这套业务数据上运行会清空表的 `scripts/smoke_e2e.ps1`。

新增聊天页面位于后台“与知识助手聊天”。服务号接入、偏好记忆及公众号所需公网回调配置见 [微信聊天接入手册](WECHAT_CHAT.md)。
