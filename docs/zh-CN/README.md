# knowledge-post-agent 中文说明

> 原文镜像：`README.md`
>
> 本文件是中文镜像文档，不替换仓库根目录原始 README。命令、路径、环境变量、API 路由、表名和代码标识保持原样，便于与英文原文对照。

`knowledge-post-agent` 是一个用于个性化知识内容摘要与知识推文生成的 MVP monorepo。它围绕 GoFrame、Python gRPC、LangGraph、官方 Model Context Protocol Python SDK、MySQL、Milvus 和 Neo4j 构建。

当前重点是可运行的 Python Agent Service，使用 `grpcio + protobuf`。LLM、MCP、Milvus 和 Neo4j 默认以 mock 或 memory 模式运行，方便本地开发和自动化测试。

安全加固说明见根目录 `SECURITY.md`。生产环境应为 HTTP API 设置 `GOFRAME_API_TOKEN`，并在 GoFrame 与 Python Agent 两端同时设置 `AGENT_GRPC_AUTH_TOKEN`，确保 gRPC 内部调用经过鉴权。

## 目录结构

```text
knowledge-post-agent/
├── goframe-backend/
├── python-agent/
├── mcp-servers/
├── shared/
│   ├── proto/agent.proto
│   └── sql/init.sql
├── proto/agent.proto
├── docker-compose.yml
└── README.md
```

## MySQL

启动本地 MySQL：

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
docker compose up -d mysql
```

初始化脚本为 `shared/sql/init.sql`，会创建：

- `articles`
- `posts`
- `feedback_logs`
- `run_logs`
- `task_runs`
- `task_steps`
- `user_profile_snapshot`
- `memory_compensation_tasks`
- `mcp_call_logs`

新增或升级已有数据库时，可按顺序执行 `shared/sql/migrations/` 下的 migration。Harness 任务控制层对应：

```powershell
mysql.exe -h 127.0.0.1 -P 3306 -u app knowledge_post_agent `
  < shared\sql\migrations\20260608_harness_task_control.sql
```

## GoFrame Backend

先启动 Python Agent，再启动 GoFrame：

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\goframe-backend
go mod tidy
go run .
```

默认地址：`http://127.0.0.1:8080`。

主要 API：

- `GET /health`：GoFrame 状态、MySQL ping、Python Agent `HealthCheck`。
- `POST /runs/articles`：从 YAML 读取 RSS/抓取源，抓取、去重、保存文章，调用 Python `ProcessArticles`，保存推文和运行日志，生成 Markdown。
- `GET /runs?status=running&task_type=articles&user_id=default-user`：查询 Harness 任务运行记录。
- `GET /runs/{run_id}`：查询单个任务及步骤详情。
- `POST /runs/{run_id}/cancel`：请求取消 `pending` / `running` 任务。
- `POST /runs/{run_id}/retry`：从 `failed` / `partially_completed` / `pending` 任务恢复执行。
- `POST /feedback`：保存反馈，调用 Python `ProcessFeedback`，更新画像快照。
- `GET /posts`：列出生成的推文。
- `GET /profile?user_id=default-user`：查看当前用户画像。
- `GET /profile/history?user_id=default-user&limit=20`：查看画像版本历史。
- `POST /profile/rollback`：回滚到历史画像版本并生成新版本。
- `GET /recommendations/explain?post_id=POST_UID`：查看推荐解释和排序元数据。
- `POST /profile/rebuild`：从已完成的结构化反馈重新构建用户画像。

运行一次文章处理任务：

```powershell
curl.exe -X POST http://127.0.0.1:8080/runs/articles
```

Harness 任务控制层：

- 任务状态机固定为 `pending` -> `running` -> `completed` / `failed` / `partially_completed` / `cancelled`。
- 每个步骤写入 `task_steps`，包含开始时间、完成时间、输入摘要、输出摘要、错误信息和重试次数。
- `task_runs.partial_result_json` 保存文章入库、已处理数、已保存 posts、Markdown 路径和可恢复文章快照；服务重启后会把未完成任务恢复为 `pending`，之后可用 retry API 继续。
- `harness.max_concurrent_tasks` 控制单进程并发任务数；同一用户同一任务类型只允许一个 `pending/running` 任务，`idempotency_key` 用于标识请求来源和后续审计。
- gRPC 步骤使用指数退避重试，配置项为 `harness.step_max_retries`、`harness.retry_backoff_milliseconds`、`harness.max_retry_delay_milliseconds`。
- 文章任务在调用 Python Agent 前会跳过已存在 post 的 `article_uid`，并使用基于 `article_uid` 的稳定 `post_uid`，避免重复生成文章和推文。

查询、取消和重试示例：

```powershell
curl.exe "http://127.0.0.1:8080/runs?status=partially_completed&task_type=articles"
curl.exe "http://127.0.0.1:8080/runs/articles-20260608000100-abcd1234"
curl.exe -X POST "http://127.0.0.1:8080/runs/articles-20260608000100-abcd1234/cancel"
curl.exe -X POST "http://127.0.0.1:8080/runs/articles-20260608000100-abcd1234/retry"
```

提交反馈：

```powershell
curl.exe -X POST http://127.0.0.1:8080/feedback `
  -H "Content-Type: application/json" `
  -d "{\"post_id\":\"POST_UID_FROM_GET_POSTS\",\"feedback_text\":\"摘要有用，希望多保留工程实践细节\",\"rating\":5}"
```

列出推文：

```powershell
curl.exe http://127.0.0.1:8080/posts
```

画像记忆 API：

```powershell
curl.exe "http://127.0.0.1:8080/profile?user_id=default-user"
curl.exe "http://127.0.0.1:8080/profile/history?user_id=default-user&limit=20"
curl.exe -X POST http://127.0.0.1:8080/profile/rollback `
  -H "Content-Type: application/json" `
  -d "{\"user_id\":\"default-user\",\"target_version\":1,\"reason\":\"manual_rollback\"}"
curl.exe "http://127.0.0.1:8080/recommendations/explain?post_id=POST_UID_FROM_GET_POSTS"
curl.exe -X POST http://127.0.0.1:8080/profile/rebuild `
  -H "Content-Type: application/json" `
  -d "{\"user_id\":\"default-user\"}"
```

生成的 Markdown 文件写入 `shared/outputs`。本地开发保留不会访问公网的 `mock://sample` 抓取源用于离线 smoke test；生产 Compose/Kubernetes 会挂载显式 crawler config，不依赖本地 mock 默认值。

## 可观测性

本地 Compose 栈包含 OpenTelemetry Collector、Jaeger、Prometheus、Grafana 和 Alertmanager，用于 traces、metrics、dashboards 和 alerts。

启动带可观测性的栈：

```powershell
docker compose up -d mysql embedding-mcp fetch-mcp milvus-mcp neo4j-mcp python-agent goframe-backend otel-collector jaeger prometheus alertmanager grafana
```

访问地址：

- Grafana: `http://127.0.0.1:3000`
- Prometheus: `http://127.0.0.1:9090`
- Jaeger: `http://127.0.0.1:16686`
- Alertmanager: `http://127.0.0.1:9093`
- GoFrame metrics: `http://127.0.0.1:8080/metrics`
- Python Agent metrics: `http://127.0.0.1:9101/metrics`
- MCP Server metrics: `7001-7004` 端口下的 `/metrics`

更多指标、日志字段、告警规则、端口冲突说明和本地 runbook 见 `docs/observability.md`。

## 端到端 Smoke

完整 MVP 路径：

```text
GoFrame HTTP API
-> RSS fetch
-> MySQL articles
-> Python gRPC ProcessArticles
-> LangGraph agents
-> MCP servers over stdio or Streamable HTTP
-> Python response
-> MySQL posts/run_logs/mcp_call_logs
-> shared/outputs Markdown
```

先启动 Docker Desktop，再运行：

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_e2e.ps1
```

该脚本会通过 Docker Compose 启动 MySQL，启动四个 MCP mock server，以 `MOCK_MCP=false` 启动 Python Agent，启动 GoFrame，调用 `POST /runs/articles`，并验证：

- `/health` 能调用 Python Agent `HealthCheck`。
- `POST /runs/articles` 返回 `ok=true`。
- 至少保存一条 post。
- `shared/outputs` 下存在 Markdown 文件。
- MySQL `posts` 有数据。
- MySQL `run_logs` 有步骤元数据。
- MySQL `mcp_call_logs` 有 MCP 调用记录。

运行当前所有单元检查加 E2E smoke：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\integration_test.ps1
```

示例配置文件：

- `shared/config/e2e.config.yaml`
- `shared/config/rss_sources.example.yaml`
- `shared/config/user_profile_snapshot.example.json`

强制 Python Agent 通过 Streamable HTTP 调用独立 MCP Server：

```powershell
$env:MOCK_MCP="false"
$env:EMBEDDING_MCP_TRANSPORT="streamable_http"
$env:FETCH_MCP_TRANSPORT="streamable_http"
$env:MILVUS_MCP_TRANSPORT="streamable_http"
$env:NEO4J_MCP_TRANSPORT="streamable_http"
$env:EMBEDDING_MCP_URL="http://127.0.0.1:7001/mcp"
$env:FETCH_MCP_URL="http://127.0.0.1:7002/mcp"
$env:MILVUS_MCP_URL="http://127.0.0.1:7003/mcp"
$env:NEO4J_MCP_URL="http://127.0.0.1:7004/mcp"
```

## Python Agent

安装依赖：

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

修改 `shared/proto/agent.proto` 后重新生成 Python protobuf stubs：

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
python -m grpc_tools.protoc -I shared/proto --python_out=python-agent --grpc_python_out=python-agent shared/proto/agent.proto
```

### 推荐排序

Filter Agent 使用可配置的个性化推荐排序器。分数归一化到 `0..10`，并在 workflow 和 gRPC 响应中包含逐维 `score_breakdown`、`recommendation_reasons`、`rejection_reasons` 和 `rank_position`。

GoFrame 会把这些解释字段与 `profile_version` 一起持久化到 `posts.metadata`。`GET /recommendations/explain?post_id=...` 返回已存储的元数据，因此原始任务结束后仍可审计推荐原因。

离线评估支持 Precision@K、Recall@K、NDCG@K、多样性和重复率：

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python scripts\evaluate_recommendations.py --input path\to\recommendation_eval.json --k 5
```

启动服务：

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python server.py
```

等价模块入口：

```powershell
python -m app.main
```

默认地址：`0.0.0.0:50051`。

## gRPC 调用

使用 `grpcurl` 调用 `HealthCheck`：

```powershell
grpcurl -plaintext -proto D:\projects\KnowMate\knowledge-post-agent\shared\proto\agent.proto -d "{\"client\":\"grpcurl\"}" 127.0.0.1:50051 agent.AgentService/HealthCheck
```

使用 `grpcurl` 调用 `ProcessArticles`：

```powershell
grpcurl -plaintext -proto D:\projects\KnowMate\knowledge-post-agent\shared\proto\agent.proto -d "{\"run_id\":\"demo-run\",\"user_profile_snapshot\":{\"interests\":\"AI,knowledge-management\"},\"mcp_policy\":{\"mock_transport\":true,\"enable_embedding\":true,\"enable_milvus\":true,\"enable_neo4j\":true},\"articles\":[{\"article_id\":\"a1\",\"url\":\"https://example.com/a1\",\"title\":\"Agent Workflow Notes\",\"raw_text\":\"This article explains filter, summary, rewrite, and check nodes for agent workflows.\"}]}" 127.0.0.1:50051 agent.AgentService/ProcessArticles
```

Python client 示例：

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python examples\client_example.py
```

## LLM Provider

Python Agent 的可插拔 LLM 层位于 `python-agent/app/tools/llm_tool.py`。

支持的 provider：

- `mock`：默认值，不需要 API key。
- `openai`：兼容 OpenAI `/chat/completions` 的 API。
- `claude`：预留的 Anthropic 实现接口。

`python-agent/config.yaml` 配置示例：

```yaml
llm:
  provider: mock
  openai:
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
    model: gpt-4.1-mini
  claude:
    api_key_env: ANTHROPIC_API_KEY
    model: claude-3-5-sonnet-latest
```

mock 启动：

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
$env:LLM_PROVIDER="mock"
python server.py
```

OpenAI-compatible 启动：

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
$env:LLM_PROVIDER="openai"
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_MODEL="gpt-4.1-mini"
$env:OPENAI_API_KEY="YOUR_KEY"
python server.py
```

如果设置了 `LLM_PROVIDER=openai` 但缺少配置的 API key 环境变量，Python Agent 会记录 warning，并回退到 mock provider，而不是直接崩溃。

LLM 输出使用 Pydantic schema 校验。JSON 解析或校验失败时，工具会请求 provider 修复一次；如果修复仍失败，则返回模板 fallback，并附带 `llm_fallback:*` issue。

## Python Agent Workflow

`ProcessArticles`：

```text
Filter Agent -> Summary Agent -> Rewrite Agent -> Check Agent
```

每个结果返回：

- `article_id`
- `keep`
- `score`
- `rank_position`
- `score_breakdown`
- `recommendation_reasons`
- `rejection_reasons`
- `summary`
- `post_text`
- `check_pass`
- `issues`
- `mcp_call_logs`

`ProcessFeedback`：

```text
Feedback Agent -> Memory Agent
```

响应返回：

- `sentiment`
- `extracted_feedback`
- `structured_feedback`
- `updated_profile_snapshot`
- `profile_diff`
- `mcp_call_logs`

Feedback Agent 保存原始反馈，Memory Agent 将正反馈、负反馈和风格偏好拆成结构化信号。画像更新会生成新的 `user_profile_snapshot.version`，写入 `diff_json`，并把 `structured_feedback_json` 和 `profile_version` 回写到 `feedback_logs`，用于幂等命中、版本追踪、回滚和重建。

## Skills

Skills 位于 `python-agent/app/skills`：

- `filter_skill.md`
- `summary_skill.md`
- `rewrite_post_skill.md`
- `fact_check_skill.md`
- `feedback_extract_skill.md`
- `memory_update_skill.md`
- `mcp_tool_usage_skill.md`

## 标准 MCP Client

Python Agent 使用官方 MCP Python SDK。Client 抽象位于 `python-agent/app/mcp`：

- `base_client.py`
- `sdk_transport.py`
- `policy.py`
- `embedding_client.py`
- `milvus_client.py`
- `neo4j_client.py`
- `fetch_client.py`

每个 server 独立选择 `memory`、`stdio` 或 `streamable_http`。Agent 会初始化官方 SDK `ClientSession`，启动时执行 `tools/list`，缓存发现到的 Tool schemas，并通过 `tools/call` 执行所有远程调用。Agent 代码不会直接调用 MCP Server handler 函数。

混合 transport 配置示例见 `python-agent/config.yaml`：

```yaml
mcp:
  memory_fallback: true
  servers:
    embedding-mcp:
      transport: stdio
      command: python
      args: ["../mcp-servers/embedding-mcp/server.py"]
      env:
        MCP_TRANSPORT: stdio
    fetch-mcp:
      transport: streamable_http
      url: http://127.0.0.1:7002/mcp
    milvus-mcp:
      transport: memory
    neo4j-mcp:
      transport: streamable_http
      url: http://127.0.0.1:7004/mcp
```

统一 client 会校验已发现的输入/输出 JSON Schemas，并提供 timeout、指数重试、熔断和可选 memory fallback。MCP 不可用时返回结构化失败或降级结果，不会让任务崩溃。

### MCP Tool 权限和日志

`python-agent/app/mcp/policy.py` 定义 MVP allowlist。每次 MCP 调用都会先经过 `BaseMcpClient.call_tool(...)`，然后才触发 transport。

允许的工具：

- `filter`：`embed_text`、`embed_batch`、`search_similar_memory`、`query_user_interest_graph`、`get_related_topics`
- `summary`：`fetch_webpage`、`extract_main_content`、`search_articles`
- `check`：`fetch_webpage`、`check_url_alive`、`search_similar_memory`、`semantic_deduplicate`
- `feedback`：`embed_text`、`search_similar_memory`
- `memory`：`embed_text`、`insert_memory_vector`、`search_similar_memory`、`update_user_interest_graph`、`query_user_interest_graph`、`get_related_topics`
- `output`：默认不允许任何工具。`save_markdown`、`generate_daily_report`、`generate_weekly_report`、`send_email` 等高风险工具需要显式 `MCPPolicy(..., high_risk_allowlist={...})` opt-in。

未授权调用不会发送到 MCP transport，而是返回结构化错误：

```json
{
  "error": {
    "code": "MCP_PERMISSION_DENIED",
    "message": "MCP permission denied: agent `filter` cannot call tool `fetch_webpage`"
  }
}
```

所有 MCP 调用返回以下日志字段：

- `run_id`
- `agent_name`
- `server_name`
- `tool_name`
- `request_json`
- `response_json`
- `status`: `success`、`failed` 或 `denied`
- `error_message`
- `success`
- `latency_ms`
- `attempts`
- `fallback`

`api_key`、`authorization`、`token`、`password`、`cookie` 等敏感 key 会从请求和响应日志中脱敏。GoFrame 会把 `ProcessArticles` 和 `ProcessFeedback` 收到的 protobuf 核心字段写入 MySQL `mcp_call_logs`。

## MCP Servers

独立 MCP Server 使用官方 MCP Python SDK，并暴露 `tools/list` 和 `tools/call`。默认 server transport 是 Streamable HTTP：

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\mcp-servers\embedding-mcp
$env:MCP_TRANSPORT="streamable_http"
python server.py
```

MCP endpoint 为 `http://127.0.0.1:7001/mcp`；`GET /health` 仍可用于运维检查。默认端口：

- `embedding-mcp`: `7001`
- `fetch-mcp`: `7002`
- `milvus-mcp`: `7003`
- `neo4j-mcp`: `7004`

通过 stdio 运行单个 server：

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\mcp-servers\embedding-mcp
$env:MCP_TRANSPORT="stdio"
python server.py
```

如果本地开发不想启动子进程或网络服务，把所有 server transport 保持为 `memory`。`MCP_MEMORY_FALLBACK=true` 还允许远程失败降级到进程内 memory 实现。

## 测试

推荐先安装运行依赖和开发门禁依赖：

```powershell
python -m pip install -r .\python-agent\requirements.txt -r .\mcp-servers\requirements.txt -r .\requirements-dev.txt
```

本地完整门禁入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1
```

没有 Docker、MySQL 或漏洞扫描工具时，可以先跑轻量门禁：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1 -SkipDocker -SkipIntegration -SkipE2E -SkipVulnerabilityScan
```

门禁覆盖：

- Go 单元测试：`go test ./... -coverprofile`，并运行 `go fmt` 与 `go vet`。
- Python 单元测试：`pytest python-agent/tests mcp-servers/tests --cov`，并运行 `ruff check` 与 `mypy`。
- MCP Tool 契约测试：覆盖工具发现、权限拒绝、Schema、重试、熔断、fallback 和安全策略。
- gRPC 协议兼容测试：`scripts\check_proto_contract.ps1` 检查 `shared/proto/agent.proto`、`proto/agent.proto`、Python stub 和 Go `agentpb` 契约。
- MySQL、Milvus、Neo4j 集成测试。
- E2E 测试：`scripts\smoke_e2e.ps1` 通过 Docker Compose 启动 MySQL、MCP、Python Agent、GoFrame，并调用 `/runs/articles` 验证数据库和 Markdown 输出。
- 故障注入测试：Python MCP client timeout/retry/circuit/fallback、LLM fallback、Crawler 临时失败与 robots 失败用例。
- 基准测试：`scripts\run_benchmarks.ps1` 运行 Go benchmark 和 Python 推荐排序 benchmark smoke。

CI 质量门禁位于 `.github/workflows/ci.yml`。Pull Request 和 `main` push 会执行 Go/Python 质量检查、Proto 一致性、migration 验证、Docker 镜像构建、依赖漏洞扫描、覆盖率报告上传和 E2E smoke test。测试失败时 CI 必须失败；禁止提交未同步的 Proto 生成代码；禁止提交明显密钥，`scripts\check_secrets.py` 会阻止明显真实密钥、private key 和常见云/平台 token 进入提交。

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m unittest discover -s tests

cd D:\projects\KnowMate\knowledge-post-agent\mcp-servers
python -m unittest discover -s tests
```

当前 Python 测试覆盖：

- article workflow 结构化输出。
- feedback workflow 画像更新。
- protobuf `AgentService.ProcessArticles` service call。
- LLM mock provider、OpenAI 缺 key fallback、JSON repair retry 和 fallback issue 行为。
- 官方 MCP stdio 与 Streamable HTTP sessions。
- 启动时 Tool discovery/cache、权限拒绝、Schema 校验、retry、circuit breaker、fallback 和日志脱敏。

## Production Embedding、Milvus 和 Neo4j

开发模式默认不依赖外部服务。基础 Compose 文件以以下方式启动 MCP Server：

```text
EMBEDDING_PROVIDER=memory
MILVUS_PROVIDER=memory
NEO4J_PROVIDER=memory
```

Memory mode 实现与生产 adapter 相同的稳定 ID、精确向量维度检查、结构化 metadata filters、语义去重和幂等兴趣事件。

安装生产 MCP 依赖：

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\mcp-servers
pip install -r requirements.txt
```

必要生产 secret 必须在仓库外提供：

```powershell
$env:OPENAI_API_KEY="..."
$env:MINIO_ROOT_USER="..."
$env:MINIO_ROOT_PASSWORD="..."
$env:NEO4J_PASSWORD="..."
```

不要在聊天中发送 API key，也不要提交到 `.env`。MCP provider 也支持 `OPENAI_API_KEY_FILE`、`MILVUS_TOKEN_FILE`、`NEO4J_PASSWORD_FILE`，用于挂载 Docker/Kubernetes secrets。

启动生产依赖栈和真实 MCP adapter：

```powershell
docker compose `
  -f docker-compose.yml `
  -f docker-compose.production.yml `
  --profile production `
  up -d --build
```

真实 embedding adapter 默认使用 `text-embedding-3-large`。GPT-5.5 仍是 Agent 生成/推理模型，不作为 embedding 模型使用。

非破坏性初始化或校验 Milvus 与 Neo4j：

```powershell
python .\scripts\init_memory_services.py
```

initializer 会在缺失时创建 `user_memory_vectors`，并幂等创建 Neo4j constraints/indexes。如果已有 Milvus collection 的 schema 或 embedding dimension 不兼容，初始化会失败，不会 drop 或 rebuild collection。请显式迁移，或使用新的 `MILVUS_COLLECTION`。

MCP health endpoints：

- `http://127.0.0.1:7001/health`：embedding provider/model/dimension。
- `http://127.0.0.1:7003/health`：Milvus collection/dimension。
- `http://127.0.0.1:7004/health`：Neo4j connection/database。

Memory mode 返回 HTTP `200`。如果生产依赖已配置但缺失、不可用或不兼容，则返回 HTTP `503`，同时 MCP 进程保持存活。Python Agent 会继续使用现有 timeout、retry、circuit breaker 和可选 memory fallback 行为。

运行 Docker-backed Milvus 和 Neo4j 集成测试：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\integration_test.ps1 -RealMemoryServices
```

付费 OpenAI smoke test 是 opt-in：

```powershell
$env:RUN_OPENAI_EMBEDDING_SMOKE="1"
$env:OPENAI_API_KEY="..."
cd .\mcp-servers
python -m unittest tests.test_real_services_integration.RealOpenAIEmbeddingSmokeTest -v
```

## 生产抓取器与正文处理

GoFrame 后端支持 RSS、Atom、Arxiv、GitHub Release 和 HuggingFace Papers。RSS 与 Atom 使用统一的 `feed` 类型，其余类型分别为 `arxiv`、`github_release`、`huggingface_papers`；本地开发可使用不会访问公网的 `mock` 类型。

来源通过 `crawler.sources` 配置。仅当 `crawler.sources` 缺失时，旧版 `rss.sources` 才会自动转换为 `feed` 或 `mock` 来源，避免重复抓取。开发与兼容示例见 `shared/config/rss_sources.example.yaml`；生产公开源示例见 `configs/crawler/prod.sources.example.yaml`。

生产 Compose 默认把 `configs/crawler/prod.sources.example.yaml` 只读挂载到 GoFrame 容器，并设置 `CONFIG_PATH=/app/goframe-backend/manifest/config/prod.sources.yaml`。替换真实源时，复制示例文件为受控文件，例如 `configs/crawler/prod.sources.yaml`，然后在 `configs/env/prod.env` 中设置：

```env
CRAWLER_CONFIG_PATH=./configs/crawler/prod.sources.yaml
```

Kubernetes 使用 `deploy/kubernetes/app-config.yaml` 中的 `knowmate-crawler-config` ConfigMap，并通过 `deploy/kubernetes/goframe-backend.yaml` 挂载到同一个 `CONFIG_PATH`。生产集群建议用 Kustomize、Helm 或平台 ConfigMap 管理替换 `prod.sources.yaml` 内容，不要直接启用本地 `mock://sample`。

当前生产示例只包含英文公开源，默认 enabled 的方向包括：

- arXiv 官方 export API：`cs.AI`、`cs.LG`、`cs.CL`、`cs.CV`
- GitHub Releases：OpenAI Agents Python、LangChain、Model Context Protocol Python SDK、Milvus、Neo4j
- 通用 feed：OpenAI News、LangChain Blog、Google Research、Hugging Face Blog

`huggingface_papers` 类型保留 disabled 示例。当前 adapter 需要 RSS/Atom；本机验证时 Hugging Face Daily Papers 官方页面公开可访问，但 `/papers/rss` 返回 401，所以生产启用前需要确认官方 feed/API 权限或扩展 adapter。所有真实源上线前都要由发布负责人确认授权、服务条款、robots.txt、请求频率、缓存策略和失败降级；arXiv/GitHub/博客 feed 虽然是公开默认示例，也应按目标环境的抓取频率重新复核。`CRAWLER_*` 环境变量仍会在 YAML 加载后覆盖 User-Agent、超时、重试、单主机间隔、响应大小和单次抓取规模。

抓取流程包含：

- URL 规范化，以及 URL、标题、正文哈希多级去重。
- robots.txt 缓存与检查、按主机请求频率限制。
- 可配置 User-Agent、超时、重试、指数退避和最大响应大小。
- HTML 正文提取、噪声清理、作者与发布时间识别。
- 中文、英文、混合内容识别。
- 单条或单来源失败隔离。

网页正文抓取失败但来源条目包含正文时，文章会使用来源正文回退并标记为 `partial`。完全无法获得正文时标记为 `failed`。失败原因保存在 `fetch_error_type` 和 `fetch_error`，常见分类包括 `robots_denied`、`rate_limited`、`timeout`、`dns_error`、`http_4xx`、`http_5xx`、`parse_error` 和 `content_extraction_error`。

MySQL `articles` 表同时保存 `raw_content`、`clean_content`、`content_hash`、`language` 和抓取诊断字段；`crawl_source_runs` 保存每个来源的运行状态和计数。新环境使用 `shared/sql/init.sql`，已有环境执行：

```powershell
$sql = Get-Content -Raw .\shared\sql\migrations\20260606_production_crawler.sql
$sql | docker compose exec -T mysql mysql "-uroot" "-p$env:MYSQL_ROOT_PASSWORD" knowledge_post_agent
```

抓取单元测试与集成测试全部使用 `testdata`、`mock://` 或 `httptest.Server`，不依赖公网：

```powershell
cd .\goframe-backend
go test ./internal/crawler -count=1
go test ./internal/crawler -run TestCrawlerIntegration -count=1 -v
```

## 用户画像记忆与补偿

已有环境执行用户反馈、画像版本、推荐解释和补偿任务迁移：

```powershell
$sql = Get-Content -Raw .\shared\sql\migrations\20260608_feedback_memory_profile_versioning.sql
$sql | docker compose exec -T mysql mysql "-uroot" "-p$env:MYSQL_ROOT_PASSWORD" knowledge_post_agent
```

`feedback_logs` 保存幂等键、原始反馈 JSON、结构化反馈 JSON、处理状态和画像版本；`user_profile_snapshot` 每次更新都会生成新 `version`，并保存 `base_version`、`diff_json`、`is_active` 和回滚来源；`memory_compensation_tasks` 保存 Milvus、Neo4j、MySQL 等部分失败后的重试和补偿任务。
