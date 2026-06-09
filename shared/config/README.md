# Shared Config

Common configuration is passed through environment variables. Each service also keeps a local YAML file for defaults where useful.

- Backend defaults: `goframe-backend/manifest/config/config.yaml`
- Python defaults: `python-agent/config.yaml`
- Example environment: `.env.example`

## 安全配置

生产环境必须通过环境变量提供密钥，不要把真实密钥写入 YAML 或提交到仓库。

- `GOFRAME_API_TOKEN`：开启 GoFrame HTTP API 的 Bearer token / `X-API-Key` 鉴权。
- `AGENT_GRPC_AUTH_TOKEN`：GoFrame gRPC Client 和 Python Agent 共用的内部调用 token。
- `GOFRAME_MAX_REQUEST_BODY_BYTES`：HTTP 请求体上限，默认 `1048576`。
- `GOFRAME_RATE_LIMIT_BURST`：按客户端的一分钟内存限流窗口，默认 `120`。
- `FETCH_MAX_RESPONSE_BYTES`：Fetch MCP 响应体上限，默认 `2097152`。

`fetch-mcp` 会阻断 localhost、私网、链路本地、云元数据地址以及解析到这些地址的域名。文件和邮件类 MCP 工具默认属于高风险能力，未显式 allowlist 时不可调用。

## 抓取来源配置

生产抓取来源使用 `crawler.sources`。支持的类型：

- `feed`：RSS 或 Atom
- `arxiv`
- `github_release`
- `huggingface_papers`
- `mock`：本地测试，不访问公网

`shared/config/rss_sources.example.yaml` 包含完整抓取策略与来源示例。真实公网来源默认关闭。旧版 `rss.sources` 仅在 `crawler.sources` 为空时转换为统一来源配置。

抓取策略可通过 YAML 或 `.env.example` 中的 `CRAWLER_*` 环境变量配置，包括 User-Agent、请求超时、重试、最大退避、按主机限速、最大响应大小和 robots.txt 缓存时间。

## 用户画像记忆表

`shared/sql/init.sql` 会创建用户画像记忆相关表，已有环境执行 `shared/sql/migrations/20260608_feedback_memory_profile_versioning.sql`。

- `feedback_logs`：保存原始反馈 `raw_feedback_json`、结构化反馈 `structured_feedback_json`、幂等键 `idempotency_key`、处理状态 `process_status` 和关联的 `profile_version`。
- `user_profile_snapshot`：每次画像更新写入新 `version`，保留 `base_version`、`diff_json`、`change_reason`、`is_active` 和 `rolled_back_from_version`，用于历史查看和回滚。
- `posts.metadata`：保存推荐排序解释，包括 `score`、`rank_position`、`score_breakdown`、`recommendation_reasons`、`rejection_reasons` 和 `profile_version`。
- `memory_compensation_tasks`：记录 Milvus、Neo4j、MySQL 等部分失败后的重试和补偿任务，包含目标系统、payload、重试次数和下一次重试时间。
