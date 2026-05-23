# knowledge-post-agent

MVP monorepo for a personalized knowledge-post summarization assistant built around GoFrame, Python gRPC, LangGraph, MCP-style clients, MySQL, Milvus, and Neo4j.

The current focus is a runnable Python Agent Service using `grpcio + protobuf`. LLM, MCP, Milvus, and Neo4j behavior is mocked by default.

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
- `user_profile_snapshot`
- `mcp_call_logs`

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
- `POST /feedback`: save feedback, call Python `ProcessFeedback`, update profile snapshot
- `GET /posts`: list generated posts

Run one article processing job:

```powershell
curl.exe -X POST http://127.0.0.1:8080/runs/articles
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

Generated Markdown files are written to [shared/outputs](D:/projects/KnowMate/knowledge-post-agent/shared/outputs). The default RSS source is `mock://sample`, so the MVP can run without internet access once MySQL and Python Agent are up.

## End-To-End Smoke

The full MVP path is:

```text
GoFrame HTTP API
-> RSS fetch
-> MySQL articles
-> Python gRPC ProcessArticles
-> LangGraph agents
-> MCP JSON-RPC mock servers
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

To force Python Agent to call MCP mock servers instead of in-process mock transport:

```powershell
$env:MOCK_MCP="false"
$env:EMBEDDING_MCP_URL="http://127.0.0.1:7001"
$env:FETCH_MCP_URL="http://127.0.0.1:7002"
$env:MILVUS_MCP_URL="http://127.0.0.1:7003"
$env:NEO4J_MCP_URL="http://127.0.0.1:7004"
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
- `updated_profile_snapshot`
- `mcp_call_logs`

## Skills

Skills live in [python-agent/app/skills](D:/projects/KnowMate/knowledge-post-agent/python-agent/app/skills):

- `filter_skill.md`
- `summary_skill.md`
- `rewrite_post_skill.md`
- `fact_check_skill.md`
- `feedback_extract_skill.md`
- `memory_update_skill.md`
- `mcp_tool_usage_skill.md`

## MCP Mock Clients

Python Agent uses mock MCP transport by default. Client abstractions are in [python-agent/app/mcp](D:/projects/KnowMate/knowledge-post-agent/python-agent/app/mcp):

- `base_client.py`
- `policy.py`
- `embedding_client.py`
- `milvus_client.py`
- `neo4j_client.py`
- `fetch_client.py`

The transport preserves a future JSON-RPC MCP call shape and records request/response logs.

### MCP Tool Permissions And Logs

`python-agent/app/mcp/policy.py` defines the MVP allowlist. Every MCP call goes through `BaseMcpClient.call_tool(...)` before the transport is invoked.

Allowed tools:

- `filter`: `embed_text`, `embed_batch`, `search_similar_memory`, `query_user_interest_graph`, `get_related_topics`
- `summary`: `fetch_webpage`, `extract_main_content`, `search_articles`
- `check`: `fetch_webpage`, `check_url_alive`, `search_similar_memory`, `semantic_deduplicate`
- `feedback`: `embed_text`, `search_similar_memory`
- `memory`: `embed_text`, `insert_memory_vector`, `search_similar_memory`, `update_user_interest_graph`, `query_user_interest_graph`, `get_related_topics`
- `output`: `save_markdown`, `generate_daily_report`, `generate_weekly_report`, `send_email`

Unauthorized calls are not sent to MCP transport. They return a structured error:

```json
{
  "error": {
    "code": "MCP_PERMISSION_DENIED",
    "message": "MCP permission denied: agent `filter` cannot call tool `fetch_webpage`"
  }
}
```

All MCP calls return and persist these log fields:

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

GoFrame writes logs received from `ProcessArticles` and `ProcessFeedback` into MySQL `mcp_call_logs`. MCP call failure or denial is degraded into a log row and does not crash the Python workflow.

## MCP Mock Servers

Standalone HTTP mock servers are still available:

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\mcp-servers\embedding-mcp
python server.py
```

Default ports:

- `embedding-mcp`: `7001`
- `fetch-mcp`: `7002`
- `milvus-mcp`: `7003`
- `neo4j-mcp`: `7004`

## Tests

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\python-agent
python -m unittest discover -s tests
```

The current Python tests cover:

- article workflow structured output
- feedback workflow profile update
- protobuf `AgentService.ProcessArticles` service call
- LLM mock provider, OpenAI missing-key fallback, JSON repair retry, and fallback issue behavior
