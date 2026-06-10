# knowledge-post-agent

MVP monorepo for a personalized knowledge-post summarization assistant built around GoFrame, Python gRPC, LangGraph, the official Model Context Protocol Python SDK, MySQL, Milvus, and Neo4j.

The current focus is a runnable Python Agent Service using `grpcio + protobuf`. LLM, MCP, Milvus, and Neo4j behavior is mocked by default.

Security hardening notes are in [SECURITY.md](D:/projects/KnowMate/knowledge-post-agent/SECURITY.md). In production, set `GOFRAME_API_TOKEN` for the HTTP API and `AGENT_GRPC_AUTH_TOKEN` on both GoFrame and Python Agent so gRPC calls are authenticated.

## Layout

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

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
docker compose up -d mysql
```

The init script is [shared/sql/init.sql](D:/projects/KnowMate/knowledge-post-agent/shared/sql/init.sql). It creates:

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

Start Python Agent first, then start GoFrame:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\goframe-backend
go mod tidy
go run .
```

Default address: `http://127.0.0.1:8080`.

APIs:

- `GET /health`: GoFrame status, MySQL ping, Python Agent `HealthCheck`
- `POST /runs/articles`: read RSS sources from YAML, fetch, dedupe, save articles, call Python `ProcessArticles`, save posts, write run logs, generate Markdown
- `GET /runs?status=running&task_type=articles&user_id=default-user`: 查询 Harness 任务运行记录
- `GET /runs/{run_id}`: 查询单个任务及步骤详情
- `POST /runs/{run_id}/cancel`: 请求取消 pending/running 任务
- `POST /runs/{run_id}/retry`: 从 failed/partially_completed/pending 的任务恢复执行
- `POST /feedback`: save feedback, call Python `ProcessFeedback`, update profile snapshot
- `GET /posts`: list generated posts
- `GET /profile?user_id=default-user`: 查看当前用户画像
- `GET /profile/history?user_id=default-user&limit=20`: 查看画像版本历史
- `POST /profile/rollback`: 回滚到历史画像版本并生成新版本
- `GET /recommendations/explain?post_id=POST_UID`: 查看推荐解释和排序元数据
- `POST /profile/rebuild`: 从已完成的结构化反馈重新构建用户画像

Run one article processing job:

```powershell
curl.exe -X POST http://127.0.0.1:8080/runs/articles
```

Harness 任务控制层：

- 任务状态机固定为 `pending` -> `running` -> `completed` / `failed` / `partially_completed` / `cancelled`。
- 每个步骤会写入 `task_steps`，包含开始时间、完成时间、输入摘要、输出摘要、错误信息和重试次数。
- `task_runs.partial_result_json` 保存文章入库、已处理数、已保存 posts、Markdown 路径和可恢复文章快照；服务重启后会把未完成任务恢复为 `pending`，之后可用 retry API 继续。
- `harness.max_concurrent_tasks` 控制单进程并发任务数；同一用户同一任务类型只允许一个 `pending/running` 任务，`idempotency_key` 用于标识请求来源和后续审计。
- gRPC 步骤使用指数退避重试，配置项为 `harness.step_max_retries`、`harness.retry_backoff_milliseconds`、`harness.max_retry_delay_milliseconds`。
- 文章任务在调用 Python Agent 前会跳过已经存在 post 的 `article_uid`，并使用基于 `article_uid` 的稳定 `post_uid`，避免重复生成文章和推文。

查询、取消和重试示例：

```powershell
curl.exe "http://127.0.0.1:8080/runs?status=partially_completed&task_type=articles"
curl.exe "http://127.0.0.1:8080/runs/articles-20260608000100-abcd1234"
curl.exe -X POST "http://127.0.0.1:8080/runs/articles-20260608000100-abcd1234/cancel"
curl.exe -X POST "http://127.0.0.1:8080/runs/articles-20260608000100-abcd1234/retry"
```

Send feedback:

```powershell
curl.exe -X POST http://127.0.0.1:8080/feedback `
  -H "Content-Type: application/json" `
  -d "{\"post_id\":\"POST_UID_FROM_GET_POSTS\",\"feedback_text\":\"摘要有用，希望多保留工程实践细节\",\"rating\":5}"
```

List posts:

```powershell
curl.exe http://127.0.0.1:8080/posts
```

Profile memory APIs:

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

Generated Markdown files are written to [shared/outputs](D:/projects/KnowMate/knowledge-post-agent/shared/outputs). Local development keeps a disabled-network `mock://sample` source for offline smoke tests; production Compose/Kubernetes mounts an explicit crawler config instead of relying on that local mock default.

## Observability

The local Compose stack includes OpenTelemetry Collector, Jaeger, Prometheus, Grafana, and Alertmanager for traces, metrics, dashboards, and alerts.

Start the observability-enabled stack:

```powershell
docker compose up -d mysql embedding-mcp fetch-mcp milvus-mcp neo4j-mcp python-agent goframe-backend otel-collector jaeger prometheus alertmanager grafana
```

Open Grafana at http://127.0.0.1:3000, Prometheus at http://127.0.0.1:9090, Jaeger at http://127.0.0.1:16686, and Alertmanager at http://127.0.0.1:9093. Metrics are exposed by GoFrame at http://127.0.0.1:8080/metrics, Python Agent at http://127.0.0.1:9101/metrics, and the MCP servers at ports 7001-7004 under `/metrics`.

More metrics, log fields, alert rules, port-conflict notes, and the local runbook are in [docs/observability.md](docs/observability.md).

## End-To-End Smoke

The full MVP path is:

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

Start Docker Desktop first, then run:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_e2e.ps1
```

The script starts MySQL through Docker Compose, starts all four MCP mock servers, starts Python Agent with `MOCK_MCP=false`, starts GoFrame, calls `POST /runs/articles`, verifies:

- `/health` can call Python Agent `HealthCheck`
- `POST /runs/articles` returns `ok=true`
- at least one post is saved
- a Markdown file exists under `shared/outputs`
- MySQL `posts` has rows
- MySQL `run_logs` has step metadata
- MySQL `mcp_call_logs` has MCP call rows

Run all current unit checks plus E2E smoke:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\integration_test.ps1
```

Example config files:

- [shared/config/e2e.config.yaml](D:/projects/KnowMate/knowledge-post-agent/shared/config/e2e.config.yaml)
- [shared/config/rss_sources.example.yaml](D:/projects/KnowMate/knowledge-post-agent/shared/config/rss_sources.example.yaml)
- [shared/config/user_profile_snapshot.example.json](D:/projects/KnowMate/knowledge-post-agent/shared/config/user_profile_snapshot.example.json)

To force Python Agent to call the standalone MCP servers over Streamable HTTP:

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

Install dependencies:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Regenerate Python protobuf stubs after editing [shared/proto/agent.proto](D:/projects/KnowMate/knowledge-post-agent/shared/proto/agent.proto):

```powershell
cd D:\projects\KnowMate\knowledge-post-agent
python -m grpc_tools.protoc -I shared/proto --python_out=python-agent --grpc_python_out=python-agent shared/proto/agent.proto
```

### Recommendation Ranking

Filter Agent uses a configurable personalized recommendation ranker. Scores are normalized to `0..10` and include per-dimension `score_breakdown`, `recommendation_reasons`, `rejection_reasons`, and `rank_position` in workflow and gRPC responses.

GoFrame persists these explanation fields in `posts.metadata` together with `profile_version`. `GET /recommendations/explain?post_id=...` returns the stored metadata, so a recommendation can be audited after the original run has finished.

Offline evaluation supports Precision@K, Recall@K, NDCG@K, diversity, and duplicate rate:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python scripts\evaluate_recommendations.py --input path\to\recommendation_eval.json --k 5
```

Start the server:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python server.py
```

Equivalent module entrypoint:

```powershell
python -m app.main
```

Default address: `0.0.0.0:50051`.

## gRPC Calls

HealthCheck with `grpcurl`:

```powershell
grpcurl -plaintext -proto D:\projects\KnowMate\knowledge-post-agent\shared\proto\agent.proto -d "{\"client\":\"grpcurl\"}" 127.0.0.1:50051 agent.AgentService/HealthCheck
```

ProcessArticles with `grpcurl`:

```powershell
grpcurl -plaintext -proto D:\projects\KnowMate\knowledge-post-agent\shared\proto\agent.proto -d "{\"run_id\":\"demo-run\",\"user_profile_snapshot\":{\"interests\":\"AI,knowledge-management\"},\"mcp_policy\":{\"mock_transport\":true,\"enable_embedding\":true,\"enable_milvus\":true,\"enable_neo4j\":true},\"articles\":[{\"article_id\":\"a1\",\"url\":\"https://example.com/a1\",\"title\":\"Agent Workflow Notes\",\"raw_text\":\"This article explains filter, summary, rewrite, and check nodes for agent workflows.\"}]}" 127.0.0.1:50051 agent.AgentService/ProcessArticles
```

Python client example:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python examples\client_example.py
```

## LLM Provider

Python Agent has a pluggable LLM layer in [python-agent/app/tools/llm_tool.py](D:/projects/KnowMate/knowledge-post-agent/python-agent/app/tools/llm_tool.py).

Supported providers:

- `mock`: default, no API key required
- `openai`: OpenAI-compatible `/chat/completions` API
- `claude`: reserved stub interface for a future Anthropic implementation

Config example in [python-agent/config.yaml](D:/projects/KnowMate/knowledge-post-agent/python-agent/config.yaml):

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

Mock startup:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
$env:LLM_PROVIDER="mock"
python server.py
```

OpenAI-compatible startup:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
$env:LLM_PROVIDER="openai"
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_MODEL="gpt-4.1-mini"
$env:OPENAI_API_KEY="YOUR_KEY"
python server.py
```

If `LLM_PROVIDER=openai` is set but the configured API key env var is missing, Python Agent logs a warning and falls back to the mock provider instead of crashing.

LLM outputs are validated with Pydantic schemas. If JSON parsing or validation fails, the tool asks the provider for one repair attempt; if repair fails, it returns a template fallback plus an `llm_fallback:*` issue.

## Python Agent Workflow

`ProcessArticles`:

```text
Filter Agent -> Summary Agent -> Rewrite Agent -> Check Agent
```

Each result returns:

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

`ProcessFeedback`:

```text
Feedback Agent -> Memory Agent
```

The response returns:

- `sentiment`
- `extracted_feedback`
- `structured_feedback`
- `updated_profile_snapshot`
- `profile_diff`
- `mcp_call_logs`

Feedback Agent 保存原始反馈，Memory Agent 将正反馈、负反馈和风格偏好拆成结构化信号。画像更新会生成新 `user_profile_snapshot.version`，写入 `diff_json`，并把 `structured_feedback_json` 和 `profile_version` 回写到 `feedback_logs`，用于幂等命中、版本追踪、回滚和重建。

## Skills

Skills live in [python-agent/app/skills](D:/projects/KnowMate/knowledge-post-agent/python-agent/app/skills):

- `filter_skill.md`
- `summary_skill.md`
- `rewrite_post_skill.md`
- `fact_check_skill.md`
- `feedback_extract_skill.md`
- `memory_update_skill.md`
- `mcp_tool_usage_skill.md`

## Standard MCP Client

Python Agent uses the official MCP Python SDK. Client abstractions are in [python-agent/app/mcp](D:/projects/KnowMate/knowledge-post-agent/python-agent/app/mcp):

- `base_client.py`
- `sdk_transport.py`
- `policy.py`
- `embedding_client.py`
- `milvus_client.py`
- `neo4j_client.py`
- `fetch_client.py`

Each server independently selects `memory`, `stdio`, or `streamable_http`. The Agent initializes official SDK `ClientSession` instances, executes `tools/list` during startup, caches discovered Tool schemas, and uses `tools/call` for all remote calls. Agent code never calls MCP Server handler functions directly.

Mixed transport configuration in [python-agent/config.yaml](D:/projects/KnowMate/knowledge-post-agent/python-agent/config.yaml):

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

The unified client validates discovered input/output JSON Schemas, applies timeout, exponential retry, circuit breaking, and optional memory fallback. MCP unavailability returns a structured failure or degraded result and does not crash the task.

### MCP Tool Permissions And Logs

`python-agent/app/mcp/policy.py` defines the MVP allowlist. Every MCP call goes through `BaseMcpClient.call_tool(...)` before the transport is invoked.

Allowed tools:

- `filter`: `embed_text`, `embed_batch`, `search_similar_memory`, `query_user_interest_graph`, `get_related_topics`
- `summary`: `fetch_webpage`, `extract_main_content`, `search_articles`
- `check`: `fetch_webpage`, `check_url_alive`, `search_similar_memory`, `semantic_deduplicate`
- `feedback`: `embed_text`, `search_similar_memory`
- `memory`: `embed_text`, `insert_memory_vector`, `search_similar_memory`, `update_user_interest_graph`, `query_user_interest_graph`, `get_related_topics`
- `output`: none by default. High-risk tools such as `save_markdown`, `generate_daily_report`, `generate_weekly_report`, and `send_email` require an explicit `MCPPolicy(..., high_risk_allowlist={...})` opt-in.

Unauthorized calls are not sent to MCP transport. They return a structured error:

```json
{
  "error": {
    "code": "MCP_PERMISSION_DENIED",
    "message": "MCP permission denied: agent `filter` cannot call tool `fetch_webpage`"
  }
}
```

All MCP calls return these log fields:

- `run_id`
- `agent_name`
- `server_name`
- `tool_name`
- `request_json`
- `response_json`
- `status`: `success`, `failed`, or `denied`
- `error_message`
- `success`
- `latency_ms`
- `attempts`
- `fallback`

Sensitive keys such as `api_key`, `authorization`, `token`, `password`, and `cookie` are redacted from request and response logs. GoFrame writes the protobuf-supported core fields received from `ProcessArticles` and `ProcessFeedback` into MySQL `mcp_call_logs`.

## MCP Servers

The standalone servers use the official MCP Python SDK and expose `tools/list` and `tools/call`. Streamable HTTP is the default server transport:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\mcp-servers\embedding-mcp
$env:MCP_TRANSPORT="streamable_http"
python server.py
```

The MCP endpoint is `http://127.0.0.1:7001/mcp`; `GET /health` remains available for operations checks. Default ports:

- `embedding-mcp`: `7001`
- `fetch-mcp`: `7002`
- `milvus-mcp`: `7003`
- `neo4j-mcp`: `7004`

Run one server over stdio:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\mcp-servers\embedding-mcp
$env:MCP_TRANSPORT="stdio"
python server.py
```

For local development without subprocesses or network services, keep every server transport set to `memory`. `MCP_MEMORY_FALLBACK=true` additionally allows remote failures to degrade to the in-process memory implementation.

## Tests

## 本地测试与 CI 质量门禁

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

门禁覆盖以下测试层级：

- Go 单元测试：`go test ./... -coverprofile`，并运行 `go fmt` 与 `go vet`。
- Python 单元测试：`pytest python-agent/tests mcp-servers/tests --cov`，并运行 `ruff check` 与 `mypy`。
- MCP Tool 契约测试：`python-agent/tests/test_mcp_client.py`、`python-agent/tests/test_mcp_policy.py`、`mcp-servers/tests/test_http_mcp.py`、`mcp-servers/tests/test_fetch_security.py` 覆盖工具发现、权限拒绝、Schema、重试、熔断、fallback 和安全策略。
- gRPC 协议兼容测试：`scripts\check_proto_contract.ps1` 检查 `shared/proto/agent.proto`、`proto/agent.proto`、Python stub 和 Go `agentpb` 契约。
- MySQL、Milvus、Neo4j 集成测试：`scripts\verify_migrations.ps1 -RequireDatabase` 验证 MySQL migration；`scripts\integration_test.ps1 -RealMemoryServices` 启动 Docker-backed Milvus 与 Neo4j 测试。
- 端到端测试：`scripts\smoke_e2e.ps1` 通过 Docker Compose 启动 MySQL、MCP、Python Agent、GoFrame，并调用 `/runs/articles` 验证数据库和 Markdown 输出。
- 故障注入测试：现有 Python MCP client timeout/retry/circuit/fallback、LLM fallback、Crawler 临时失败与 robots 失败用例会随单元测试运行。
- 基准测试：`scripts\run_benchmarks.ps1` 运行 Go benchmark 和 Python 推荐排序 benchmark smoke。

CI 质量门禁位于 `.github/workflows/ci.yml`，Pull Request 和 `main` push 会执行 Go/Python 质量检查、Proto 一致性、migration 验证、Docker 镜像构建、依赖漏洞扫描、覆盖率报告上传和 E2E smoke test。测试失败时 CI 必须失败；禁止提交未同步的 Proto 生成代码；禁止提交明显密钥，`scripts\check_secrets.py` 会阻止明显真实密钥、private key 和常见云/平台 token 进入提交。

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m unittest discover -s tests

cd D:\projects\KnowMate\knowledge-post-agent\mcp-servers
python -m unittest discover -s tests
```

The current Python tests cover:

- article workflow structured output
- feedback workflow profile update
- protobuf `AgentService.ProcessArticles` service call
- LLM mock provider, OpenAI missing-key fallback, JSON repair retry, and fallback issue behavior
- official MCP stdio and Streamable HTTP sessions
- startup Tool discovery/cache, permission denial, Schema validation, retry, circuit breaker, fallback, and log redaction

## Production Embedding, Milvus, And Neo4j

Development remains dependency-free by default. The base Compose file starts
the MCP servers with:

```text
EMBEDDING_PROVIDER=memory
MILVUS_PROVIDER=memory
NEO4J_PROVIDER=memory
```

Memory mode implements the same stable IDs, exact vector-dimension checks,
structured metadata filters, semantic deduplication, and idempotent interest
events used by production adapters.

Install the production MCP dependencies:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\mcp-servers
pip install -r requirements.txt
```

Required production secrets must be supplied outside the repository:

```powershell
$env:OPENAI_API_KEY="..."
$env:MINIO_ROOT_USER="..."
$env:MINIO_ROOT_PASSWORD="..."
$env:NEO4J_PASSWORD="..."
```

Do not send API keys in chat or commit them to `.env`. MCP providers also
support `OPENAI_API_KEY_FILE`, `MILVUS_TOKEN_FILE`, and
`NEO4J_PASSWORD_FILE` for mounted Docker/Kubernetes secrets.

Start the production dependency stack and real MCP adapters:

```powershell
docker compose `
  -f docker-compose.yml `
  -f docker-compose.production.yml `
  --profile production `
  up -d --build
```

The real embedding adapter uses `text-embedding-3-large` by default. GPT-5.5
remains a separate Agent generation/reasoning model and is not used as an
embedding model.

Initialize or validate Milvus and Neo4j without destructive migration:

```powershell
python .\scripts\init_memory_services.py
```

The initializer creates `user_memory_vectors` when absent and creates Neo4j
constraints/indexes idempotently. If an existing Milvus collection has an
incompatible schema or embedding dimension, initialization fails without
dropping or rebuilding the collection. Migrate explicitly or use a new
`MILVUS_COLLECTION`.

MCP health endpoints:

- `http://127.0.0.1:7001/health`: embedding provider/model/dimension
- `http://127.0.0.1:7003/health`: Milvus collection/dimension
- `http://127.0.0.1:7004/health`: Neo4j connection/database

Memory mode returns HTTP `200`. A configured production dependency that is
missing, unavailable, or incompatible returns HTTP `503`, while the MCP
process remains alive. Python Agent then applies its existing timeout, retry,
circuit breaker, and optional memory fallback behavior.

Run Docker-backed Milvus and Neo4j integration tests:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\integration_test.ps1 -RealMemoryServices
```

The paid OpenAI smoke test is opt-in:

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

- URL 规范化，以及 URL、标题、正文哈希多级去重
- robots.txt 缓存与检查、按主机请求频率限制
- 可配置 User-Agent、超时、重试、指数退避和最大响应大小
- HTML 正文提取、噪声清理、作者与发布时间识别
- 中文、英文、混合内容识别
- 单条或单来源失败隔离

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
