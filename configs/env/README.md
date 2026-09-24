# 环境文件边界

每类环境变量只有一个模板来源。运行时的 `.env`、`configs/env/prod.env` 和
`.local-server/<stage>/` 文件属于本机状态，不提交，也不要反向复制回模板。

| 文件 | 唯一用途 | 维护内容 |
| --- | --- | --- |
| `.env.example` | 根目录 Compose 或本地进程的通用模板 | 数据库、GoFrame、Agent、MCP 和观测配置 |
| `configs/env/dev.env` | 开发 Compose 的可复现覆盖 | mock provider 和开发端口/凭据占位 |
| `configs/env/test.env` | 测试运行的隔离覆盖 | 测试数据库、较小任务上限和 mock provider |
| `configs/env/prod.env.example` | 生产 Compose 的非敏感模板 | Secret 文件路径、真实 provider 和生产开关 |
| `configs/env/wechat.env.example` | `scripts/local_server.py` 生成本机阶段配置 | 仅微信公众号回调和网页 OAuth 变量 |

微信公众号配置不再复制到根 `.env.example`；长期记忆服务配置只维护在根模板和
生产模板中。`scripts/local_server.py init` 会复制微信专用模板到
`.local-server/<stage>/wechat.env`，之后只编辑该阶段文件。

生产 Secret 使用 `*_FILE` 或 Secret 管理器提供，不把真实 AppSecret、Token、AES
Key、SessionSecret 写入这些模板。
