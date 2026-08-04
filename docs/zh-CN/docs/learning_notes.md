# KnowMate 学习笔记草稿

> 原文镜像：`docs/learning_notes.md`
>
> 原文件已以中文为主；本镜像保留命令、路径、代码块和协议字段原样。


> 这份笔记基于当前仓库代码编写，目标是帮助初学者按“整体 -> 调用链 -> 模块 -> 函数”的顺序理解 KnowMate。
> 重要边界: 当前项目是 MVP。GoFrame HTTP、MySQL、gRPC、Python Workflow、Markdown 输出是真实可运行链路；LLM 默认是 mock；MCP、Milvus、Neo4j 默认是 mock 或内存模拟；Claude provider 只是预留接口。

## 第一部分: 项目总体介绍

KnowMate 是一个“个性化知识文章处理助手”。它从 RSS 来源抓文章，把文章保存到 MySQL，然后调用 Python Agent Service 对文章做筛选、总结、改写和检查，最后把生成的知识帖保存到 MySQL 并输出 Markdown。

它解决的问题是: 信息源很多，人工筛选和总结成本高；同时每个人偏好不同，系统需要根据用户画像和反馈逐渐调整推荐、总结和改写方式。

项目拆成几个部分，是为了把不同职责隔离清楚:

- `goframe-backend/`: 面向用户的 HTTP API、RSS 抓取、MySQL 持久化、gRPC 客户端、Markdown 输出。它是“业务入口和数据落库层”。
- `python-agent/`: Agent 编排、LangGraph 工作流、LLM 调用、MCP Client。它是“智能处理层”。
- `mcp-servers/`: 独立的 HTTP JSON-RPC mock MCP Server，模拟 embedding、fetch、Milvus、Neo4j 等外部工具。它是“外部工具协议演示层”。
- `shared/`: 共享协议、SQL、配置示例、输出目录。它是“跨语言契约和共享资源层”。
- `proto/`: `shared/proto/agent.proto` 的兼容副本，用来检查 proto 同步。

当前 MVP 中的真实实现:

- GoFrame HTTP 服务: `goframe-backend/main.go`、`internal/handler/handler.go`。
- MySQL 表结构和读写: `shared/sql/init.sql`、`goframe-backend/internal/store/mysql.go`。
- Go -> Python gRPC 调用: `goframe-backend/internal/grpcclient/client.go`、`python-agent/app/grpc_server.py`。
- Python Agent Workflow: `python-agent/app/workflow/graph.py`。
- Markdown 文件输出: `goframe-backend/internal/logic/harness/harness.go` 的 `writeMarkdown`。
- RSS 真实抓取能力: `goframe-backend/internal/crawler/rss.go` 使用 `gofeed`，但默认配置是 `mock://sample`。

当前 MVP 中的 mock 或预留:

- LLM 默认 mock: `python-agent/app/tools/llm_tool.py` 的 `MockLLMClient`。
- OpenAI provider 可真实调用，但缺 key 时自动 fallback 到 mock。
- Claude provider 是 stub: `ClaudeLLMClient.complete_json` 直接抛出未实现错误。
- MCP 默认 in-process mock: `MockMcpTransport`。
- 独立 MCP Servers 是 HTTP mock server，不是真实 Milvus/Neo4j。
- Milvus 逻辑是内存向量模拟: `mcp-servers/milvus-mcp/server.py`。
- Neo4j 逻辑是内存图模拟: `mcp-servers/neo4j-mcp/server.py`。

## 第二部分: 项目目录结构讲解

当前目录树:

```text
KnowMate/
├── README.md
├── docker-compose.yml
├── .env.example
├── goframe-backend/
│   ├── main.go
│   ├── go.mod
│   ├── go.sum
│   ├── manifest/config/config.yaml
│   └── internal/
│       ├── agentpb/
│       │   ├── agent.pb.go
│       │   ├── agent_grpc.pb.go
│       │   └── proto_contract_test.go
│       ├── config/config.go
│       ├── crawler/rss.go
│       ├── grpcclient/client.go
│       ├── handler/handler.go
│       ├── logic/harness/harness.go
│       ├── model/model.go
│       └── store/mysql.go
├── python-agent/
│   ├── server.py
│   ├── config.yaml
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── agent_pb2.py
│   ├── agent_pb2_grpc.py
│   ├── examples/client_example.py
│   ├── tools/llm_tool.py
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── contracts.py
│   │   ├── grpc_server.py
│   │   ├── skill_loader.py
│   │   ├── agents/
│   │   ├── llm/
│   │   ├── mcp/
│   │   ├── skills/
│   │   ├── tools/
│   │   └── workflow/
│   └── tests/
├── mcp-servers/
│   ├── README.md
│   ├── common/simple_http_mcp.py
│   ├── embedding-mcp/
│   ├── fetch-mcp/
│   ├── milvus-mcp/
│   └── neo4j-mcp/
├── shared/
│   ├── proto/agent.proto
│   ├── sql/init.sql
│   ├── config/
│   └── outputs/
├── proto/agent.proto
└── scripts/
    ├── check_proto_contract.ps1
    ├── integration_test.ps1
    └── smoke_e2e.ps1
```

全文件速览:

| 文件                                                        | 作用                                                                                                                          |
| ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `.env.example`                                            | 环境变量示例，包含 GoFrame、Python Agent、MCP endpoint 配置。                                                                 |
| `README.md`                                               | 项目总入口文档，说明 MVP 边界、启动、gRPC、LLM、MCP、测试。                                                                   |
| `docker-compose.yml`                                      | 启动 MySQL，并挂载 `shared/sql/init.sql` 初始化表。                                                                         |
| `goframe-backend/main.go`                                 | GoFrame 后端入口。                                                                                                            |
| `goframe-backend/go.mod` / `go.sum`                     | Go 模块依赖。                                                                                                                 |
| `goframe-backend/manifest/config/config.yaml`             | GoFrame 默认配置。                                                                                                            |
| `goframe-backend/internal/agentpb/agent.pb.go`            | proto 生成的 Go message 类型。                                                                                                |
| `goframe-backend/internal/agentpb/agent_grpc.pb.go`       | proto 生成的 Go gRPC client/server 接口。                                                                                     |
| `goframe-backend/internal/agentpb/proto_contract_test.go` | Go 侧 proto 契约测试。                                                                                                        |
| `goframe-backend/internal/config/config.go`               | 后端配置读取、环境变量覆盖、默认值归一化。                                                                                    |
| `goframe-backend/internal/crawler/rss.go`                 | RSS 抓取、mock RSS、文章去重。                                                                                                |
| `goframe-backend/internal/grpcclient/client.go`           | 连接 Python Agent 的 gRPC client。                                                                                            |
| `goframe-backend/internal/handler/handler.go`             | HTTP handler/controller。                                                                                                     |
| `goframe-backend/internal/logic/harness/harness.go`       | 文章处理和反馈处理的主编排。                                                                                                  |
| `goframe-backend/internal/model/model.go`                 | Go 侧业务模型。                                                                                                               |
| `goframe-backend/internal/store/mysql.go`                 | MySQL 读写层。                                                                                                                |
| `mcp-servers/README.md`                                   | MCP mock servers 总说明。                                                                                                     |
| `mcp-servers/common/simple_http_mcp.py`                   | 通用 HTTP JSON-RPC MCP server 框架。                                                                                          |
| `mcp-servers/embedding-mcp/README.md` / `server.py`     | embedding mock server 文档和实现。                                                                                            |
| `mcp-servers/fetch-mcp/README.md` / `server.py`         | fetch mock/真实网页抓取 server 文档和实现。                                                                                   |
| `mcp-servers/milvus-mcp/README.md` / `server.py`        | Milvus mock vector memory server 文档和实现。                                                                                 |
| `mcp-servers/neo4j-mcp/README.md` / `server.py`         | Neo4j mock user graph server 文档和实现。                                                                                     |
| `proto/agent.proto`                                       | proto 兼容副本，用于同步检查。                                                                                                |
| `python-agent/server.py`                                  | Python Agent 主入口。                                                                                                         |
| `python-agent/config.yaml`                                | Python Agent 默认配置。                                                                                                       |
| `python-agent/pyproject.toml` / `requirements.txt`      | Python 依赖定义。                                                                                                             |
| `python-agent/agent_pb2.py`                               | proto 生成的 Python message 类型。                                                                                            |
| `python-agent/agent_pb2_grpc.py`                          | proto 生成的 Python gRPC stub/servicer 基类。                                                                                 |
| `python-agent/examples/client_example.py`                 | Python gRPC 调用示例。                                                                                                        |
| `python-agent/tools/llm_tool.py`                          | 兼容旧路径的 re-export。                                                                                                      |
| `python-agent/app/__init__.py`                            | Python package 标记文件。                                                                                                     |
| `python-agent/app/main.py`                                | `python -m app.main` 入口。                                                                                                 |
| `python-agent/app/config.py`                              | Python 配置加载。                                                                                                             |
| `python-agent/app/contracts.py`                           | 共享 dict 类型、run_id、policy、article 标准化。                                                                              |
| `python-agent/app/grpc_server.py`                         | Python gRPC Server 实现。                                                                                                     |
| `python-agent/app/skill_loader.py`                        | 读取 skills markdown。                                                                                                        |
| `python-agent/app/agents/base.py`                         | Agent 基类。                                                                                                                  |
| `python-agent/app/agents/__init__.py`                     | Agent 导出集合。                                                                                                              |
| `python-agent/app/agents/filter_agent.py`                 | FilterAgent。                                                                                                                 |
| `python-agent/app/agents/summary_agent.py`                | SummaryAgent。                                                                                                                |
| `python-agent/app/agents/rewrite_agent.py`                | RewriteAgent。                                                                                                                |
| `python-agent/app/agents/check_agent.py`                  | CheckAgent。                                                                                                                  |
| `python-agent/app/agents/feedback_agent.py`               | FeedbackAgent。                                                                                                               |
| `python-agent/app/agents/memory_agent.py`                 | MemoryAgent。                                                                                                                 |
| `python-agent/app/llm/__init__.py` / `mock.py`          | 旧版 mock LLM 类，目前主流程使用 `app/tools/llm_tool.py`。                                                                  |
| `python-agent/app/mcp/__init__.py`                        | MCP Client 导出集合。                                                                                                         |
| `python-agent/app/mcp/base_client.py`                     | MCP transport、client 基类、日志生成和降级。                                                                                  |
| `python-agent/app/mcp/policy.py`                          | MCP 权限矩阵。                                                                                                                |
| `python-agent/app/mcp/embedding_client.py`                | Embedding MCP Client。                                                                                                        |
| `python-agent/app/mcp/fetch_client.py`                    | Fetch MCP Client。                                                                                                            |
| `python-agent/app/mcp/milvus_client.py`                   | Milvus MCP Client。                                                                                                           |
| `python-agent/app/mcp/neo4j_client.py`                    | Neo4j MCP Client。                                                                                                            |
| `python-agent/app/tools/__init__.py`                      | LLMTool 相关类导出。                                                                                                          |
| `python-agent/app/tools/llm_tool.py`                      | LLM provider、Pydantic schema、JSON repair、fallback。                                                                        |
| `python-agent/app/workflow/__init__.py`                   | Workflow 导出。                                                                                                               |
| `python-agent/app/workflow/graph.py`                      | ArticleWorkflow 和 LangGraph/sequential 编排。                                                                                |
| `python-agent/app/workflow/state.py`                      | AgentState 类型。                                                                                                             |
| `python-agent/app/skills/*.md`                            | Agent skill/prompt/权限/失败处理说明，其中短文件如 `summary.md` 是简版说明，`summary_skill.md` 是主流程读取的详细 skill。 |
| `python-agent/tests/test_workflow.py`                     | Workflow 和 gRPC service 测试。                                                                                               |
| `python-agent/tests/test_llm_tool.py`                     | LLMTool 测试。                                                                                                                |
| `python-agent/tests/test_mcp_policy.py`                   | MCP 权限和日志测试。                                                                                                          |
| `python-agent/tests/test_skills.py`                       | Skill 文件完整性测试。                                                                                                        |
| `scripts/check_proto_contract.ps1`                        | proto 同步和契约检查。                                                                                                        |
| `scripts/integration_test.ps1`                            | Go test + Python unit test + smoke。                                                                                          |
| `scripts/smoke_e2e.ps1`                                   | 完整 E2E smoke。                                                                                                              |
| `shared/proto/agent.proto`                                | gRPC 主契约。                                                                                                                 |
| `shared/sql/init.sql`                                     | MySQL schema。                                                                                                                |
| `shared/config/README.md`                                 | 共享配置说明。                                                                                                                |
| `shared/config/e2e.config.yaml`                           | E2E 配置示例。                                                                                                                |
| `shared/config/rss_sources.example.yaml`                  | RSS source 配置示例。                                                                                                         |
| `shared/config/user_profile_snapshot.example.json`        | 用户画像示例。                                                                                                                |
| `shared/outputs/.gitkeep`                                 | 输出目录占位。                                                                                                                |

### `goframe-backend/`

职责: 提供 HTTP API，负责 RSS 抓取、去重、MySQL 写入、调用 Python gRPC、保存结果、生成 Markdown。

重要文件:

- `main.go`: GoFrame 服务入口，加载配置，初始化 MySQL schema，注册 HTTP handler。
- `internal/handler/handler.go`: HTTP controller 层，注册 `/health`、`/runs/articles`、`/feedback`、`/posts`、`/run-logs`。
- `internal/logic/harness/harness.go`: 业务编排层，文章处理和反馈处理的主流程都在这里。
- `internal/crawler/rss.go`: RSS 抓取与 mock RSS 数据。
- `internal/store/mysql.go`: MySQL 数据访问层，相当于本项目里的 DAO。
- `internal/model/model.go`: Go 侧数据模型。
- `internal/grpcclient/client.go`: Go gRPC client，调用 Python `AgentService`。
- `internal/agentpb/*.go`: 从 proto 生成的 Go 类型和 gRPC stub。
- `manifest/config/config.yaml`: 后端默认配置。

协作方式:

```text
main.go
-> config.Load
-> store.New / InitSchema
-> harness.New
-> handler.New / Register
-> HTTP 请求进 handler
-> handler 调 harness
-> harness 调 crawler/store/grpcclient
```

初学者阅读顺序:

1. `main.go`
2. `internal/handler/handler.go`
3. `internal/logic/harness/harness.go`
4. `internal/store/mysql.go`
5. `internal/crawler/rss.go`
6. `internal/grpcclient/client.go`
7. `internal/model/model.go`
8. `internal/agentpb/proto_contract_test.go`

### `python-agent/`

职责: Python gRPC Server，接收 GoFrame 请求，运行 Agent Workflow，调用 LLMTool 和 MCP Client，返回结构化结果。

重要文件:

- `server.py`: Python Agent 启动入口。
- `app/main.py`: 模块入口，等价于 `python -m app.main`。
- `app/grpc_server.py`: 实现 proto 里的 `AgentService`。
- `app/workflow/graph.py`: `ArticleWorkflow`，组织 LangGraph 或 sequential fallback。
- `app/workflow/state.py`: LangGraph state 类型。
- `app/agents/*.py`: 六个 Agent。
- `app/tools/llm_tool.py`: LLM provider、结构化输出、JSON repair、fallback。
- `app/mcp/*.py`: MCP client、transport、权限策略、调用日志。
- `app/skills/*.md`: Agent 的提示词和工具使用约束。
- `tests/*.py`: Python 单元测试。
- `agent_pb2.py`、`agent_pb2_grpc.py`: 从 proto 生成的 Python 类型和 gRPC stub。

协作方式:

```text
server.py
-> load_settings
-> serve
-> AgentService
-> ArticleWorkflow
-> Filter/Summary/Rewrite/Check 或 Feedback/Memory
-> LLMTool / MCP Client
-> gRPC Response
```

初学者阅读顺序:

1. `server.py`
2. `app/grpc_server.py`
3. `app/workflow/graph.py`
4. `app/workflow/state.py`
5. `app/agents/filter_agent.py`
6. `app/agents/summary_agent.py`
7. `app/agents/rewrite_agent.py`
8. `app/agents/check_agent.py`
9. `app/agents/feedback_agent.py`
10. `app/agents/memory_agent.py`
11. `app/tools/llm_tool.py`
12. `app/mcp/base_client.py` 和 `app/mcp/policy.py`

### `mcp-servers/`

职责: 提供四个独立的 HTTP JSON-RPC mock MCP Server。只有当 Python Agent 使用 `MOCK_MCP=false` 时，才会通过 HTTP 调用它们；默认 `MOCK_MCP=true` 时使用 Python 进程内的 `MockMcpTransport`，不需要启动这些 server。

重要文件:

- `common/simple_http_mcp.py`: 通用 HTTP JSON-RPC server 框架。
- `embedding-mcp/server.py`: mock embedding。
- `fetch-mcp/server.py`: mock 或真实网页 fetch。
- `milvus-mcp/server.py`: 内存 mock vector store。
- `neo4j-mcp/server.py`: 内存 mock user interest graph。
- 各目录 `README.md`: 说明端口、工具和请求格式。

协作方式:

```text
Python BaseMcpClient
-> JsonRpcMcpTransport
-> http://127.0.0.1:7001/7002/7003/7004/rpc
-> simple_http_mcp.run_server
-> 各 server.py handle
```

初学者阅读顺序:

1. `mcp-servers/README.md`
2. `common/simple_http_mcp.py`
3. `embedding-mcp/server.py`
4. `milvus-mcp/server.py`
5. `neo4j-mcp/server.py`
6. `fetch-mcp/server.py`

### `shared/`

职责: 放跨服务共享的契约、SQL、配置示例和输出目录。

重要文件:

- `shared/proto/agent.proto`: Go 和 Python 共享 gRPC 契约。
- `shared/sql/init.sql`: MySQL 表结构。
- `shared/config/e2e.config.yaml`: E2E 配置示例。
- `shared/config/rss_sources.example.yaml`: RSS 配置示例。
- `shared/config/user_profile_snapshot.example.json`: 用户画像示例。
- `shared/outputs/.gitkeep`: Markdown 输出目录占位。

初学者阅读顺序:

1. `shared/proto/agent.proto`
2. `shared/sql/init.sql`
3. `shared/config/user_profile_snapshot.example.json`
4. `shared/config/e2e.config.yaml`

### `proto/`

职责: 存放 `agent.proto` 的兼容副本。`scripts/check_proto_contract.ps1` 会比较 `proto/agent.proto` 和 `shared/proto/agent.proto` 是否一致。

初学者阅读顺序: 主要看 `shared/proto/agent.proto`，把 `proto/agent.proto` 理解为同步校验副本即可。

### `scripts/`

职责: 自动化检查和端到端 smoke。

重要文件:

- `smoke_e2e.ps1`: 启动 MySQL、MCP mock servers、Python Agent、GoFrame，然后调用 `/runs/articles` 并验证数据库和 Markdown。
- `integration_test.ps1`: 先跑 Go 测试、Python 单元测试，再跑 E2E smoke。
- `check_proto_contract.ps1`: 检查 proto 文件同步，以及 Python/Go 生成代码包含必要字段和 RPC。

初学者阅读顺序:

1. `scripts/smoke_e2e.ps1`
2. `scripts/integration_test.ps1`
3. `scripts/check_proto_contract.ps1`

### `docker-compose.yml`

职责: 只启动 MySQL 8.0，并挂载 `shared/sql/init.sql` 作为初始化脚本。没有启动 GoFrame、Python Agent 或 MCP Server，这些需要本机命令或脚本启动。

### `README.md`

职责: 项目总说明。它写清楚了 MVP 边界、启动方式、gRPC 示例、LLM Provider、MCP 权限和测试命令。初学者第一天只看它就够了。

## 第三部分: 启动流程讲解

### 1. MySQL 如何启动

命令:

```powershell
docker compose up -d mysql
```

`docker-compose.yml` 使用 `mysql:8.0`，创建数据库 `knowledge_post_agent`，用户 `app/apppass`，root 密码 `rootpass`，并把 `./shared/sql/init.sql` 挂载到 `/docker-entrypoint-initdb.d/01-init.sql`。

为什么先启动 MySQL: GoFrame 启动时会 `store.InitSchema`，并且 `/runs/articles`、`/feedback` 都要写表。如果 MySQL 不可用，后端能启动但接口会失败，`/health` 的 `db.status` 会是 `unavailable`。

### 2. Python Agent Service 如何启动

安装依赖:

```powershell
cd python-agent
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

启动:

```powershell
python server.py
```

或者:

```powershell
python -m app.main
```

默认监听 `0.0.0.0:50051`。入口链路是:

```text
server.py main()
-> load_settings()
-> serve(settings)
-> create_server(settings)
-> add_AgentServiceServicer_to_server
-> server.start()
```

### 3. MCP mock servers 如何启动

默认 `MOCK_MCP=true` 时不需要启动 MCP Server，Python Agent 会使用进程内 `MockMcpTransport`。

如果想走 HTTP JSON-RPC mock servers:

```powershell
cd mcp-servers\embedding-mcp
python server.py

cd mcp-servers\fetch-mcp
python server.py

cd mcp-servers\milvus-mcp
python server.py

cd mcp-servers\neo4j-mcp
python server.py
```

默认端口:

- embedding: `7001`
- fetch: `7002`
- milvus: `7003`
- neo4j: `7004`

同时启动 Python Agent 时设置:

```powershell
$env:MOCK_MCP="false"
$env:EMBEDDING_MCP_URL="http://127.0.0.1:7001"
$env:FETCH_MCP_URL="http://127.0.0.1:7002"
$env:MILVUS_MCP_URL="http://127.0.0.1:7003"
$env:NEO4J_MCP_URL="http://127.0.0.1:7004"
python server.py
```

注意: proto 里的 `McpPolicy.mock_transport` 当前没有真正决定 transport。实际 transport 在 `ArticleWorkflow.__init__` 里由 Python setting `settings.mock_mcp` 决定，也就是环境变量 `MOCK_MCP`。

### 4. GoFrame Backend 如何启动

```powershell
cd goframe-backend
go mod tidy
go run .
```

默认地址: `http://127.0.0.1:8080`。

为什么最后启动 GoFrame: GoFrame 的 `/health` 要检查 MySQL 和 Python Agent；`/runs/articles` 要先写 MySQL，再 gRPC 调 Python。

### 5. `smoke_e2e.ps1` 做了什么

`scripts/smoke_e2e.ps1` 是完整 MVP 路径验证:

1. `docker compose up -d mysql`。
2. 等待 MySQL ready。
3. 清理 `shared/outputs/articles-*.md`。
4. 启动 4 个 MCP mock servers。
5. 等待 4 个 `/health`。
6. 用 `MOCK_MCP=false`、`MOCK_LLM=true` 启动 Python Agent。
7. 启动 GoFrame Backend。
8. 调 `/health`，确认 Python Agent 返回 `SERVING`。
9. 调 `POST /runs/articles`。
10. 断言 `ok=true`。
11. 断言至少保存一个 post。
12. 断言 Markdown 文件存在。
13. 调 `/posts`，断言有数据。
14. 查询 MySQL `posts`、`run_logs`、`mcp_call_logs`，确认落库。
15. 默认结束时停止它启动的子进程。

### 6. `integration_test.ps1` 做了什么

`scripts/integration_test.ps1` 做三件事:

```text
go test ./...
-> python -m unittest discover -s tests
-> scripts/smoke_e2e.ps1
```

它比 smoke 更全面，因为会先跑 Go/Python 单元测试，再跑完整 E2E。

服务依赖关系:

```text
MySQL
  ↑
GoFrame Backend
  ↓
Python Agent Service
  ↓ 当 MOCK_MCP=false
MCP mock servers
```

## 第四部分: gRPC 接口讲解

核心文件: `shared/proto/agent.proto`。`proto3` 表示使用 Protocol Buffers 第 3 版语法。`package agent` 表示 gRPC 包名是 `agent`。`option go_package` 指定 Go 生成代码包路径。

### `AgentService` 定义了哪些 RPC

```proto
service AgentService {
  rpc HealthCheck(HealthCheckRequest) returns (HealthCheckResponse);
  rpc ProcessArticles(ProcessArticlesRequest) returns (ProcessArticlesResponse);
  rpc ProcessFeedback(ProcessFeedbackRequest) returns (ProcessFeedbackResponse);
}
```

- `HealthCheck`: GoFrame 检查 Python Agent 是否可用。
- `ProcessArticles`: 文章处理主流程。
- `ProcessFeedback`: 用户反馈闭环流程。

### `HealthCheck`

Request:

- `client`: 调用方名字。GoFrame 用的是 `"goframe-backend"`，Python example 用的是 `"python-example"`。

Response:

- `status`: Python 服务状态，当前返回 `"SERVING"`。
- `version`: Python Agent 版本，来自 `settings.version`。
- `enabled_agents`: 当前启用的 Agent 名称，来自 `ArticleWorkflow.enabled_agents()`。
- `mock_mode`: 只要 LLM provider 是 mock 或 MCP 是 mock，就返回 true。

Python 实现: `python-agent/app/grpc_server.py` 的 `HealthCheck`。
Go 调用: `goframe-backend/internal/grpcclient/client.go` 的 `HealthCheck`。

### `ProcessArticles`

Request:

- `run_id`: 一次运行的 ID，由 GoFrame 在 `newRunID("articles")` 创建。
- `articles`: 文章数组，每个元素是 `Article`。
- `user_profile_snapshot`: `map<string,string>`，用户画像快照，比如 `interests`。
- `mcp_policy`: 控制是否启用 embedding、fetch、Milvus、Neo4j 等工具信号。

`Article` 字段:

- `article_id`: 文章唯一 ID。GoFrame 从 RSS item 生成或使用 mock ID。
- `url`: 原文链接。
- `title`: 标题。
- `raw_text`: 原文正文。GoFrame 从 RSS content/description 填入。
- `source`: RSS source 名称。
- `published_at`: 发布时间字符串。
- `tags`: 标签数组。

Response:

- `run_id`: 原样返回。
- `results`: 每篇文章一个 `ArticleProcessResult`。

`ArticleProcessResult` 字段:

- `article_id`: 对应输入文章。
- `keep`: Filter 是否保留。
- `score`: Filter 打分。
- `summary`: Summary Agent 生成的摘要。
- `post_text`: Rewrite Agent 生成的 Markdown 正文。
- `check_pass`: Check Agent 是否通过。
- `issues`: 机器可读问题列表。
- `mcp_call_logs`: MCP 调用日志，GoFrame 会写入 MySQL `mcp_call_logs`。

GoFrame 如何根据 proto 调 Python:

```text
shared/proto/agent.proto
-> protoc 生成 goframe-backend/internal/agentpb/*.go
-> grpcclient.New 创建 AgentServiceClient
-> harness.callProcessArticles 构造 ProcessArticlesRequest
-> client.ProcessArticles
```

关键代码:

- `goframe-backend/internal/logic/harness/harness.go`: `callProcessArticles`、`toProtoArticles`。
- `goframe-backend/internal/grpcclient/client.go`: `ProcessArticles`。

Python 如何根据 proto 实现 gRPC Server:

```text
shared/proto/agent.proto
-> protoc 生成 python-agent/agent_pb2.py 和 agent_pb2_grpc.py
-> AgentService 继承 agent_pb2_grpc.AgentServiceServicer
-> 实现 ProcessArticles
-> create_server 注册到 grpc.Server
```

关键代码:

- `python-agent/app/grpc_server.py`: `AgentService.ProcessArticles`。

### `ProcessFeedback`

Request:

- `run_id`: 反馈运行 ID。
- `feedback`: `FeedbackItem` 数组。
- `user_profile_snapshot`: 当前用户画像快照。
- `mcp_policy`: MCP 工具开关。

`FeedbackItem` 字段:

- `feedback_id`: 单条反馈 ID。
- `user_id`: 用户 ID。
- `article_id`: 关联文章 ID。
- `post_id`: 关联生成帖 ID。
- `feedback_text`: 用户自然语言反馈。
- `feedback_type`: 类型，默认 `"text"`。
- `rating`: 评分。
- `metadata`: 额外上下文。

Response:

- `run_id`: 原样返回。
- `sentiment`: `positive`、`neutral` 或 `negative`。
- `extracted_feedback`: 抽取出的偏好信号。
- `updated_profile_snapshot`: 更新后的画像快照。
- `mcp_call_logs`: 反馈流程中的 MCP 调用日志。

## 第五部分: Python Agent Service 讲解

### 整体入口

`python-agent/server.py`:

```text
main()
-> logging.basicConfig
-> load_settings()
-> serve(settings)
```

`python-agent/app/main.py` 很薄，只是导入 `server.main`，让你可以用 `python -m app.main` 启动。

`python-agent/app/config.py` 读取:

- `python-agent/config.yaml`
- 环境变量 `AGENT_HOST`、`AGENT_PORT`、`MOCK_MCP`、`LLM_PROVIDER`、`OPENAI_API_KEY` 等

### gRPC Server 如何接收请求

`app/grpc_server.py` 中:

- `AgentService.__init__`: 创建一个 `ArticleWorkflow`。
- `HealthCheck`: 返回服务状态。
- `ProcessArticles`: 把 protobuf request 转成普通 Python dict，调用 `workflow.process_articles`，再把结果转回 protobuf response。
- `ProcessFeedback`: 同理，转 dict -> workflow -> protobuf response。
- `create_server`: 创建 `grpc.server`，注册 servicer。
- `serve`: 监听地址并阻塞等待。

### 请求如何进入 `ArticleWorkflow`

文章请求链路:

```text
AgentService.ProcessArticles
-> self.workflow.process_articles(dict_request)
-> ArticleWorkflow.process_articles
-> LangGraph invoke 或 sequential fallback
-> 返回 dict
-> AgentService 转 ProcessArticlesResponse
```

反馈请求链路:

```text
AgentService.ProcessFeedback
-> self.workflow.process_feedback(dict_request)
-> Feedback Agent
-> Memory Agent
-> 返回 dict
-> AgentService 转 ProcessFeedbackResponse
```

### `ArticleWorkflow` 如何组织 LangGraph

`python-agent/app/workflow/graph.py` 的 `ArticleWorkflow.__init__` 做了这些事:

1. `load_skills()` 读取 `app/skills/*.md`。
2. 根据 `settings.mock_mcp` 选择 `MockMcpTransport` 或 `JsonRpcMcpTransport`。
3. 创建 `MCPPolicy`。
4. 创建 `EmbeddingClient`、`FetchClient`、`MilvusClient`、`Neo4jClient`。
5. 创建 `LLMTool`。
6. 创建 6 个 Agent。
7. 尝试构建 article LangGraph。
8. 尝试构建 feedback LangGraph。

### LangGraph 不存在时为什么还能 sequential fallback

`_try_build_article_langgraph` 和 `_try_build_feedback_langgraph` 都写了:

```python
try:
    from langgraph.graph import END, StateGraph
except ImportError:
    return None
```

如果没有安装 `langgraph`，函数返回 `None`。后续 `process_articles` 里会判断:

```python
result = self._article_graph.invoke(state) if self._article_graph else self._run_article_sequential(state)
```

意思是: 有 LangGraph 就用 graph，没有就按列表顺序手动调用 Agent。这样 MVP 在依赖不完整时也能跑。

### 重点文件

- `app/workflow/graph.py`: 工作流总控。
- `app/workflow/state.py`: 定义 state 允许有哪些 key。
- `app/agents/`: 每个 Agent 的本地逻辑。
- `app/tools/llm_tool.py`: 所有 LLM 调用统一走这里。
- `app/mcp/`: 所有 MCP 调用统一走这里。
- `app/skills/`: prompt 和工具约束文档。

## 第六部分: LangGraph 工作流讲解

### 文章处理流程

```text
入口 state
  |
  v
Filter Agent
  |
  v
Summary Agent
  |
  v
Rewrite Agent
  |
  v
Check Agent
  |
  v
END
  |
  v
ProcessArticlesResponse
```

### 反馈处理流程

```text
入口 state
  |
  v
Feedback Agent
  |
  v
Memory Agent
  |
  v
END
  |
  v
ProcessFeedbackResponse
```

### state 字段

`python-agent/app/workflow/state.py`:

- `run_id`: 本次运行 ID。
- `articles`: 输入文章列表。
- `feedback`: 输入反馈列表。
- `user_profile_snapshot`: 用户画像快照。
- `mcp_policy`: MCP 工具开关。
- `article_results`: 文章处理中间和最终结果。
- `sentiment`: 反馈情绪。
- `extracted_feedback`: 抽取出的反馈信号。
- `updated_profile_snapshot`: 更新后的用户画像。
- `mcp_call_logs`: 反馈流程全局 MCP 日志。

### Agent 读写 state

| Agent         | 读取                                                                                         | 写入                                                                                   |
| ------------- | -------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| FilterAgent   | `run_id`、`articles`、`user_profile_snapshot`、`mcp_policy`                          | `article_results`，每个 result 带 `keep`、`score`、`issues`、`mcp_call_logs` |
| SummaryAgent  | `user_profile_snapshot`、`article_results[*].article`、`keep`                          | `article_results[*].summary`、可能追加 `issues`                                    |
| RewriteAgent  | `article_results[*].article`、`summary`、`keep`                                        | `article_results[*].post_text`、可能追加 `issues`                                  |
| CheckAgent    | `article_results[*]`                                                                       | `article_results[*].check_pass`、规范化 `issues`                                   |
| FeedbackAgent | `feedback`                                                                                 | `sentiment`、`extracted_feedback`、可能写 `feedback_issues`                      |
| MemoryAgent   | `run_id`、`user_profile_snapshot`、`sentiment`、`extracted_feedback`、`mcp_policy` | `updated_profile_snapshot`、`mcp_call_logs`                                        |

### 最终结果如何转成 gRPC Response

`ArticleWorkflow.process_articles` 返回普通 dict:

```text
{
  "run_id": "...",
  "results": [...]
}
```

`AgentService.ProcessArticles` 遍历 `results`，每一项构造成 `agent_pb2.ArticleProcessResult`。

`ArticleWorkflow.process_feedback` 返回:

```text
{
  "run_id": "...",
  "sentiment": "...",
  "extracted_feedback": [...],
  "updated_profile_snapshot": {...},
  "mcp_call_logs": [...]
}
```

`AgentService.ProcessFeedback` 构造成 `agent_pb2.ProcessFeedbackResponse`。

### LangGraph 节点、边、入口、END

`_try_build_article_langgraph`:

- `StateGraph(AgentState)`: 创建有类型提示的状态图。
- `add_node("filter", self.filter_agent.run)`: 节点就是 Agent 的 `run` 函数。
- `set_entry_point("filter")`: 入口节点是 Filter。
- `add_edge("filter", "summary")`: Filter 完成后进入 Summary。
- `add_edge("check", END)`: Check 完成后结束。
- `graph.compile()`: 编译成可 `invoke(state)` 的图。

## 第七部分: Agent 逐个讲解

### 1. FilterAgent

【Agent 作用】
FilterAgent 负责判断文章是否值得继续处理。当前 MVP 主要用本地规则打分，并可叠加 mock Neo4j 画像上下文、mock embedding、mock Milvus 相似记忆信号。

【输入】
读取 `state["run_id"]`、`state["articles"]`、`state["user_profile_snapshot"]`、`state["mcp_policy"]`。如果启用 MCP，还会通过 `EmbeddingClient`、`MilvusClient`、`Neo4jClient`、可选 `FetchClient` 获取辅助信号。

【处理流程】

1. 遍历每篇文章。
2. 如果允许 fetch 且文章没有正文，尝试调用 fetch。注意: Filter 的 MCP 权限禁止 `fetch_webpage`，所以这种调用会被 policy 拒绝并产生日志。
3. 用 `_score_article` 做本地打分。
4. 如果允许 Neo4j，调用 `query_user_interest_graph`，有 topics 就加 0.05。
5. 如果允许 embedding，调用 `embed_text`。
6. 如果允许 Milvus 且有 embedding，调用 `search_similar_memory`，有 matches 就加 0.05。
7. `score >= 0.5` 且有标题则 `keep=true`。
8. 写入 `state["article_results"]`。

【输出】
`state["article_results"]`。每个 result 包括 `article`、`article_id`、`keep`、`score`、`summary`、`post_text`、`check_pass`、`issues`、`mcp_call_logs`、`filter_reasons`。

【调用的工具】
不调用 LLM。会调用 MCP Client。会读取 Skill 文本但当前代码没有把 skill_text 用进打分逻辑。不会更新用户画像。

【核心函数逐行讲解: `filter_agent.py` 的 `run`, 第 28-81 行】

| 行    | 解释                                                                                                                                                              |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 28    | `def run(self, state: JsonDict) -> JsonDict:` 定义实例方法。`self` 是当前 Agent 对象，`state` 是工作流共享字典，`-> JsonDict` 是 Python 类型标注。        |
| 29    | `run_id = str(state.get("run_id", ""))` 从 state 取运行 ID。`dict.get(key, default)` 表示 key 不存在时用默认值。`str(...)` 保证后续日志字段是字符串。       |
| 30    | `profile = state.get("user_profile_snapshot", {})` 取用户画像。默认空 dict，避免没有画像时报错。                                                                |
| 31    | `policy = state.get("mcp_policy", {})` 取 MCP 开关，比如是否启用 embedding、Milvus、Neo4j。                                                                     |
| 32    | `article_results = []` 创建空列表，用来收集每篇文章的处理结果。                                                                                                 |
| 33    | `for article in state.get("articles", []):` 遍历输入文章。`for ... in ...` 是 Python 循环语法；默认空列表可避免无文章时报错。                                 |
| 34    | `logs: list[JsonDict] = []` 为当前文章创建 MCP 日志列表。`list[JsonDict]` 是类型提示。                                                                        |
| 35    | `if policy.get("enable_fetch") ...:` 判断是否允许 fetch、文章是否没有正文、是否有 URL、是否注入了 fetch client。多个条件用 `and`，全部为真才进入。            |
| 36    | `fetched = self.fetch_client.fetch_url(...)` 调用 FetchClient。当前权限矩阵中 filter 不允许 `fetch_webpage`，所以如果真的走到这里，会得到 denied 日志。       |
| 37    | `logs.append(fetched.log)` 把 MCP 调用日志加入当前文章日志。`append` 是列表追加方法。                                                                         |
| 38    | `article["raw_text"] = ...` 把 fetch 结果里的 `raw_text` 写回 article。即使为空也转成字符串。                                                                 |
| 40    | `score, reasons = self._score_article(article, profile)` 调用本地打分函数。左侧是元组解包，把返回的两个值分别赋给 `score` 和 `reasons`。                    |
| 41    | `if policy.get("enable_neo4j") and self.neo4j_client:` 如果开了 Neo4j 且 client 存在，进入图画像查询。                                                          |
| 42    | `context = self.neo4j_client.get_profile_context(...)` 调用 `query_user_interest_graph`，传用户 ID、画像、agent_name、run_id。                                |
| 43    | `logs.append(context.log)` 保存 Neo4j 调用日志。                                                                                                                |
| 44    | `if context.result.get("topics"):` 如果返回 topics，说明有图画像上下文。                                                                                        |
| 45    | `score = min(score + 0.05, 1.0)` 分数加 0.05，但用 `min` 限制最高 1.0。                                                                                       |
| 46    | `reasons.append("mock-profile-context")` 记录加分原因。这里明确是 mock 信号。                                                                                   |
| 48    | `embedding: list[float] = []` 初始化 embedding 为空列表。类型提示表示列表元素是 float。                                                                         |
| 49    | `if policy.get("enable_embedding") and self.embedding_client:` 如果允许 embedding 且 client 存在，开始向量化。                                                  |
| 50-54 | `embedded = self.embedding_client.embed_text(...)` 多行函数调用。把标题和正文拼成一个字符串，并传 `agent_name`、`run_id` 用于权限和日志。                   |
| 55    | `logs.append(embedded.log)` 保存 embedding 调用日志。                                                                                                           |
| 56    | `embedding = list(embedded.result.get("embedding", []))` 从结果中取 embedding；`list(...)` 确保是列表。失败时 result 是 error，没有 embedding，则得到空列表。 |
| 58    | `if policy.get("enable_milvus") and embedding and self.milvus_client:` 只有允许 Milvus、embedding 非空、client 存在时才查相似记忆。                             |
| 59    | `related = self.milvus_client.search_similar_memory(...)` 调用 mock/真实 transport 的 `search_similar_memory`。                                               |
| 60    | `logs.append(related.log)` 保存 Milvus 调用日志。                                                                                                               |
| 61    | `if related.result.get("matches"):` 如果有相似记忆命中。                                                                                                        |
| 62    | `score = min(score + 0.05, 1.0)` 再加 0.05，同样限制最高 1.0。                                                                                                  |
| 63    | `reasons.append("mock-related-articles")` 记录相似记忆加分原因。这里也是 mock 信号。                                                                            |
| 65    | `keep = score >= 0.5 and bool(article.get("title"))` 得出是否保留。`>=` 是比较运算，`bool(...)` 把标题存在性转布尔值。                                      |
| 66    | `article_results.append(` 开始把本篇文章结果追加到列表。                                                                                                        |
| 67-78 | 这是一个字典 literal，保存文章、ID、保留结果、分数、摘要占位、推文占位、检查状态、问题列表、MCP 日志和筛选原因。                                                  |
| 71    | `round(score, 4)` 把分数保留 4 位小数。                                                                                                                         |
| 75    | `"issues": [] if keep else ["filtered_out"]` 是 Python 三元表达式。保留则无问题，不保留则标记 `filtered_out`。                                                |
| 80    | `state["article_results"] = article_results` 把所有文章结果写回工作流 state。                                                                                   |
| 81    | `return state` 返回更新后的 state，让下一个 Agent 继续处理。                                                                                                    |

### 2. SummaryAgent

【Agent 作用】
SummaryAgent 负责为保留下来的文章生成中文摘要。

【输入】
读取 `state["user_profile_snapshot"]`、`state["article_results"]`、每个 result 的 `article` 和 `keep`。读取 `summary_skill.md`，传给 LLMTool。

【处理流程】

1. 复制用户画像。
2. 遍历文章结果。
3. 跳过 `keep=false` 的文章。
4. 调用 `llm_tool.summarize(article, profile, skill_text)`。
5. 写入 `summary`。
6. 如果 LLM 输出有 issues，追加到 result 的 issues。

【输出】
写入 `result["summary"]`，可能追加 `result["issues"]`。

【调用的工具】
调用 LLMTool。当前代码不调用 MCP。读取 Skill。

【核心函数逐行讲解: `summary_agent.py` 的 `run`, 第 16-25 行】

| 行 | 解释                                                                                                                                             |
| -- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| 16 | 定义 `run` 方法，输入输出都是 `JsonDict`。                                                                                                   |
| 17 | `profile = dict(state.get("user_profile_snapshot", {}))` 取画像并复制成新 dict。`dict(...)` 可以避免直接改原对象。                           |
| 18 | `for result in state.get("article_results", []):` 遍历 FilterAgent 生成的结果。                                                                |
| 19 | `if not result.get("keep"):` 如果文章不保留。`not` 是布尔取反。                                                                              |
| 20 | `continue` 跳过本次循环，进入下一篇文章。                                                                                                      |
| 21 | `output = self.llm_tool.summarize(...)` 调 LLMTool。参数包括文章、画像和 summary skill 文本。                                                  |
| 22 | `result["summary"] = output.summary` 把 Pydantic 输出对象里的 `summary` 写回 result。                                                        |
| 23 | `if output.issues:` 如果 LLMTool 返回问题，例如 fallback。空列表在 Python 中为 false。                                                         |
| 24 | `result.setdefault("issues", []).extend(output.issues)` 如果没有 `issues` 就创建空列表，然后追加 LLM 问题。`extend` 会把列表元素逐个追加。 |
| 25 | `return state` 返回更新后的 state。                                                                                                            |

### 3. RewriteAgent

【Agent 作用】
RewriteAgent 把摘要改写成适合发布的 Markdown 知识帖。

【输入】
读取每个 result 的 `article`、`summary`、`keep`。读取 `rewrite_post_skill.md`，传给 LLMTool。

【处理流程】

1. 遍历文章结果。
2. 跳过不保留的文章。
3. 调用 `llm_tool.rewrite_post(article, summary, skill_text)`。
4. 写入 `post_text`。
5. 追加 issues。

【输出】
写入 `result["post_text"]`，可能追加 `result["issues"]`。

【调用的工具】
调用 LLMTool。当前代码不调用 MCP。读取 Skill。不更新用户画像。

【核心函数逐行讲解: `rewrite_agent.py` 的 `run`, 第 16-24 行】

| 行 | 解释                                                                                                                 |
| -- | -------------------------------------------------------------------------------------------------------------------- |
| 16 | 定义 `run` 方法，接收工作流 state。                                                                                |
| 17 | 遍历 `article_results`。                                                                                           |
| 18 | 如果 `keep` 不是 true，说明 Filter 不推荐继续处理。                                                                |
| 19 | `continue` 跳过该文章。                                                                                            |
| 20 | 调用 `llm_tool.rewrite_post`。`str(result.get("summary", ""))` 确保 summary 是字符串，即使缺失也不会报类型错误。 |
| 21 | 把返回对象的 `post_text` 写入 result。                                                                             |
| 22 | 如果 LLMTool 返回 issues。                                                                                           |
| 23 | 用 `setdefault(...).extend(...)` 把问题追加到现有 issues。                                                         |
| 24 | 返回 state。                                                                                                         |

### 4. CheckAgent

【Agent 作用】
CheckAgent 负责检查最终结果是否满足最低发布要求。当前 MVP 只做本地字段检查: 是否保留、是否有 summary、是否有 post_text、是否有 URL。

【输入】
读取 `article_results`、每个 result 的 `keep`、`summary`、`post_text`、`issues` 和 `article.url`。

【处理流程】

1. 遍历每个 result。
2. 复制已有 issues。
3. 如果不保留，直接 `check_pass=false`。
4. 如果缺 summary，追加 `missing_summary`。
5. 如果缺 post_text，追加 `missing_post_text`。
6. 如果缺 URL，追加 `missing_url`。
7. 没有任何 issues 时 `check_pass=true`。

【输出】
写入 `result["issues"]` 和 `result["check_pass"]`。

【调用的工具】
当前代码不调用 LLM、不调用 MCP、不读取 skill_text 的内容。`fact_check_skill.md` 设计了更完整的事实检查、URL 检查和去重，但 MVP 代码还没有实现这些增强能力。

【核心函数逐行讲解: `check_agent.py` 的 `run`, 第 10-26 行】

| 行 | 解释                                                                                                            |
| -- | --------------------------------------------------------------------------------------------------------------- |
| 10 | 定义 `run` 方法。                                                                                             |
| 11 | 遍历 `article_results`。                                                                                      |
| 12 | `issues = list(result.get("issues", []))` 复制已有问题列表。`list(...)` 避免直接操作原列表引用。            |
| 13 | `article = result.get("article", {})` 取原文章信息。                                                          |
| 14 | `if not result.get("keep"):` 如果不保留。                                                                     |
| 15 | `result["check_pass"] = False` 不保留的文章不算通过检查。                                                     |
| 16 | `result["issues"] = issues` 保留已有问题。                                                                    |
| 17 | `continue` 跳过后续检查。                                                                                     |
| 18 | `if not result.get("summary"):` 检查摘要是否为空。                                                            |
| 19 | `issues.append("missing_summary")` 记录缺摘要。                                                               |
| 20 | `if not result.get("post_text"):` 检查 Markdown 正文是否为空。                                                |
| 21 | `issues.append("missing_post_text")` 记录缺正文。                                                             |
| 22 | `if not article.get("url"):` 检查文章 URL。                                                                   |
| 23 | `issues.append("missing_url")` 记录缺 URL。                                                                   |
| 24 | `result["issues"] = issues` 把最终问题列表写回 result。                                                       |
| 25 | `result["check_pass"] = len(issues) == 0` 如果问题数量为 0，就通过。`len` 返回列表长度，`==` 是相等比较。 |
| 26 | `return state` 返回 state。                                                                                   |

### 5. FeedbackAgent

【Agent 作用】
FeedbackAgent 负责从用户自然语言反馈中抽取结构化偏好信号，并判断情绪倾向。

【输入】
读取 `state["feedback"]` 和 `feedback_extract_skill.md`。调用 LLMTool。

【处理流程】

1. 调用 `llm_tool.extract_feedback`。
2. 写入 `sentiment`。
3. 写入 `extracted_feedback`。
4. 如果有 issues，写入 `feedback_issues`。

【输出】
写入 `state["sentiment"]`、`state["extracted_feedback"]`、可选 `state["feedback_issues"]`。

【调用的工具】
调用 LLMTool。当前代码不调用 MCP；Feedback skill 中允许的 embedding/search_similar_memory 暂未在 FeedbackAgent 中实现。不会直接更新用户画像，画像更新由 MemoryAgent 做。

【核心函数逐行讲解: `feedback_agent.py` 的 `run`, 第 16-22 行】

| 行 | 解释                                                                                                                  |
| -- | --------------------------------------------------------------------------------------------------------------------- |
| 16 | 定义 `run` 方法。                                                                                                   |
| 17 | `output = self.llm_tool.extract_feedback(...)` 把反馈列表和 skill_text 交给 LLMTool。`list(...)` 确保输入是列表。 |
| 18 | `state["sentiment"] = output.sentiment` 写入情绪。                                                                  |
| 19 | `state["extracted_feedback"] = output.extracted_feedback` 写入抽取出的偏好信号。                                    |
| 20 | `if output.issues:` 如果结构化输出有问题。                                                                          |
| 21 | `state["feedback_issues"] = output.issues` 把问题写到 state。                                                       |
| 22 | 返回 state 给 MemoryAgent。                                                                                           |

### 6. MemoryAgent

【Agent 作用】
MemoryAgent 负责把反馈结果更新到用户画像快照，并通过 MCP 记录 embedding 和 Neo4j interest graph 更新。当前 MVP 没有真正写 Milvus 向量，只调用了 embedding 和 Neo4j update。

【输入】
读取 `run_id`、`user_profile_snapshot`、`extracted_feedback`、`sentiment`、`mcp_policy`。使用 `EmbeddingClient` 和 `Neo4jClient`。

【处理流程】

1. 复制当前 snapshot。
2. 读取反馈抽取结果和情绪。
3. 初始化或取得全局 `mcp_call_logs`。
4. 如果允许 embedding，调用 `embed_text` 记录反馈向量化日志。
5. 更新本地 snapshot 的 `last_feedback_sentiment`。
6. 累加 `feedback_count`。
7. 如果有反馈，写入最近三条 `latest_feedback`。
8. 如果允许 Neo4j，调用 `update_user_interest_graph`。
9. 写回 `updated_profile_snapshot`。

【输出】
写入 `state["updated_profile_snapshot"]` 和 `state["mcp_call_logs"]`。

【调用的工具】
不调用 LLM。调用 MCP Client。读取 skill_text 但当前没有使用其中规则做复杂画像合并。会更新用户画像快照。

【核心函数逐行讲解: `memory_agent.py` 的 `run`, 第 22-48 行】

| 行    | 解释                                                                                                                                 |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------ |
| 22    | 定义 `run` 方法。                                                                                                                  |
| 23    | 从 state 取 run_id，并转字符串。                                                                                                     |
| 24    | `snapshot = dict(...)` 复制用户画像，避免直接改原对象。                                                                            |
| 25    | `extracted = list(...)` 取抽取出的反馈信号并保证是列表。                                                                           |
| 26    | `sentiment = str(...)` 取情绪，默认 `neutral`。                                                                                  |
| 27    | `logs = state.setdefault("mcp_call_logs", [])` 如果 state 没有 `mcp_call_logs`，就创建空列表；如果已有就返回已有列表。           |
| 29    | 判断是否存在 embedding_client 且 policy 允许 embedding。                                                                             |
| 30-35 | 调用 `embed_text`。第 31 行把所有 feedback 用空格拼成一个字符串；第 32 行传 metadata；第 33-34 行传 agent_name 和 run_id。         |
| 36    | 把 embedding MCP 调用日志追加到全局 logs。                                                                                           |
| 38    | `snapshot["last_feedback_sentiment"] = sentiment` 更新最近反馈情绪。                                                               |
| 39    | 更新 `feedback_count`。这里用 `int(...)` 把字符串计数转整数，加上本次抽取条数，再转回字符串，符合 proto `map<string,string>`。 |
| 40    | `if extracted:` 如果存在抽取结果。                                                                                                 |
| 41    | `snapshot["latest_feedback"] = "                                                                                                     |
| 43    | 判断是否存在 neo4j_client 且 policy 允许 Neo4j。                                                                                     |
| 44    | 调用 `update_profile`，底层 tool 是 `update_user_interest_graph`。                                                               |
| 45    | 追加 Neo4j MCP 调用日志。                                                                                                            |
| 47    | `state["updated_profile_snapshot"] = snapshot` 把新画像写入 state。                                                                |
| 48    | 返回 state。                                                                                                                         |

## 第八部分: LLM 调用层讲解

核心文件: `python-agent/app/tools/llm_tool.py`。

### 1. `LLM_PROVIDER` 如何选择

`app/config.py` 的 `_load_llm_settings` 决定 provider:

1. 先读 `config.yaml` 的 `llm.provider`。
2. 如果没有 provider，则根据 `mock.llm` 决定 mock 或 openai。
3. 如果环境变量 `LLM_PROVIDER` 存在，覆盖配置。
4. 如果 `MOCK_LLM` 存在且为 true，强制 provider 为 mock。

### 2. mock provider 怎么工作

`MockLLMClient.complete_json` 根据 `task` 返回 JSON 字符串:

- `summary`: 取文章标题和正文前 180 字，返回 `{"summary": "...", "issues": []}`。
- `rewrite`: 拼出 `【知识笔记】标题`、摘要、关注点和原文链接。
- `feedback`: 根据 rating 和关键词粗略判断 positive/neutral/negative，并抽取反馈文本。

它不访问外部网络，不需要 API key。

### 3. openai provider 怎么工作

`OpenAICompatibleLLMClient.complete_json`:

1. 拼 endpoint: `base_url.rstrip("/") + "/chat/completions"`。
2. 构造 request body: model、messages、temperature、`response_format={"type":"json_object"}`。
3. 用 `urllib.request` POST。
4. 读取 `choices[0].message.content`。

它是 OpenAI-compatible API，并不绑定某个特定模型服务。

### 4. Claude provider 当前状态

`ClaudeLLMClient.complete_json` 当前直接:

```python
raise RuntimeError("Claude provider interface is reserved but not implemented in this MVP")
```

也就是说有类和配置，但没有真实 Anthropic API 调用实现。

### 5. API key 如何读取

OpenAI:

- 默认 env 名是 `OPENAI_API_KEY`。
- 可以通过 `OPENAI_API_KEY_ENV` 改成别的环境变量名。
- `build_llm_client` 用 `os.getenv(settings.openai.api_key_env, "")` 读取。

Claude:

- 默认 env 名是 `ANTHROPIC_API_KEY`。

如果 OpenAI 或 Claude 缺 key，`build_llm_client` 会 warning 并返回 `MockLLMClient`，不让服务崩溃。

### 6. JSON 输出如何校验

`LLMTool._generate_structured` 的核心链路:

```text
provider.complete_json
-> _parse_json
-> _validate_schema
-> 返回 Pydantic output object
```

`_parse_json` 先 `json.loads(raw.strip())`。如果失败，会尝试从文本中找第一个 `{` 和最后一个 `}`，截出 JSON object 再解析。

### 7. Pydantic schema 如何保证结构化输出

三个 schema:

- `SummaryLLMOutput`: `summary` 必须至少 1 个字符，`issues` 默认空列表。
- `RewriteLLMOutput`: `post_text` 必须至少 1 个字符。
- `FeedbackLLMOutput`: `sentiment` 限制为 `positive|neutral|negative`，`extracted_feedback` 默认空列表。

`schema.model_validate(value)` 会检查字段类型、必填和约束。

### 8. JSON 解析失败时如何 repair

第一次解析或校验失败后:

```text
LOGGER.warning
-> 构造 repair_prompt
-> 再调用同一个 provider.complete_json
-> 再 parse + validate
```

repair prompt 会带上 schema 字段、原始 payload、上一次错误。

### 9. repair 失败时如何 fallback

如果修复也失败:

```text
issue = "llm_fallback:{provider}:{error_type}"
-> 调 fallback lambda
-> fallback lambda 使用 MockLLMClient 生成模板结果
-> issues 里带 fallback issue
```

这样 Summary/Rewrite/Feedback 不会因为 LLM 输出坏掉而让整个 workflow 崩溃。

### 10. 哪些 Agent 会调用 LLM

- SummaryAgent: 调 `llm_tool.summarize`。
- RewriteAgent: 调 `llm_tool.rewrite_post`。
- FeedbackAgent: 调 `llm_tool.extract_feedback`。

FilterAgent、CheckAgent、MemoryAgent 当前不调用 LLM。

### Summary Agent 调用 LLM 完整链路

```text
SummaryAgent.run
-> 读取 state["user_profile_snapshot"]
-> 遍历 state["article_results"]
-> 跳过 keep=false
-> llm_tool.summarize(article, profile, summary_skill.md)
-> LLMTool._generate_structured
-> provider.complete_json
   - mock: MockLLMClient
   - openai: /chat/completions
   - claude: stub, 会失败
-> _parse_json
-> SummaryLLMOutput.model_validate
-> result["summary"] = output.summary
-> output.issues 追加到 result["issues"]
-> 返回 state
```

## 第九部分: MCP 机制讲解

核心目录: `python-agent/app/mcp/`。

### 1. `base_client.py` 的作用

`base_client.py` 定义 MCP 调用的通用框架:

- `McpTransport`: transport 协议接口。
- `McpCallResult`: 统一返回 `result` 和 `log`。
- `MockMcpTransport`: 进程内 mock transport。
- `JsonRpcMcpTransport`: HTTP JSON-RPC transport。
- `BaseMcpClient`: 所有具体 MCP Client 的父类，负责权限检查、调用 transport、生成日志和降级错误。

### 2. `policy.py` 的作用

`policy.py` 定义 Agent 到 tool 的 allowlist。每次调用都走:

```text
BaseMcpClient.call_tool
-> self.policy.check(agent_name, tool_name)
```

如果没有权限，不会调用 transport，直接返回 `MCP_PERMISSION_DENIED` 日志。

### 3. 各 Client 分别负责什么

- `EmbeddingClient`: `embed_text`、`embed_batch`。
- `FetchClient`: `fetch_webpage`、`extract_main_content`、`clean_html`、`check_url_alive`。
- `MilvusClient`: `search_similar_memory`、`insert_memory_vector`、`semantic_deduplicate`、`search_articles` 等向量/相似内容能力。
- `Neo4jClient`: `query_user_interest_graph`、`update_user_interest_graph`、`get_related_topics` 等用户兴趣图能力。

### 4. `MockMcpTransport` 是什么

`MockMcpTransport` 是 Python Agent 进程内的 mock 实现。它不走 HTTP:

- `embedding-mcp`: 根据文本长度返回 3 维 mock embedding。
- `milvus-mcp`: 返回 mock matches。
- `neo4j-mcp`: 返回 mock topics 或 updated。
- `fetch-mcp`: 返回 mock fetched document 或 URL alive。

### 5. `JsonRpcMcpTransport` 是什么

`JsonRpcMcpTransport` 把调用发到独立 MCP mock server:

```json
{
  "jsonrpc": "2.0",
  "id": "...",
  "method": "tools/call",
  "params": {
    "name": "embed_text",
    "arguments": {"text": "..."}
  }
}
```

它 POST 到 `http://host:port/rpc`，解析 JSON-RPC envelope，并取 `result.output` 作为工具结果。

### 6. `MOCK_MCP=true` 和 `MOCK_MCP=false` 的区别

- `MOCK_MCP=true`: 使用 `MockMcpTransport`，不用启动 `mcp-servers`。
- `MOCK_MCP=false`: 使用 `JsonRpcMcpTransport`，必须先启动 4 个 MCP mock servers。

再强调一次: 当前 request 里的 `mcp_policy.mock_transport` 不控制 transport，真正控制点是 Python Agent 启动时的 `settings.mock_mcp`。

### 7. MCP Tool 权限如何控制

权限矩阵在 `DEFAULT_AGENT_TOOL_PERMISSIONS`:

- `filter`: `embed_text`、`embed_batch`、`search_similar_memory`、`query_user_interest_graph`、`get_related_topics`
- `summary`: `fetch_webpage`、`extract_main_content`、`search_articles`
- `check`: `fetch_webpage`、`check_url_alive`、`search_similar_memory`、`semantic_deduplicate`
- `feedback`: `embed_text`、`search_similar_memory`
- `memory`: `embed_text`、`insert_memory_vector`、`search_similar_memory`、`update_user_interest_graph`、`query_user_interest_graph`、`get_related_topics`
- `output`: `save_markdown`、`generate_daily_report`、`generate_weekly_report`、`send_email`

### 8. 未授权工具调用会发生什么

如果 `filter` 调 `fetch_webpage`:

```text
MCPPolicy.check
-> not allowed
-> BaseMcpClient 不调用 transport
-> result.error.code = MCP_PERMISSION_DENIED
-> log.status = denied
-> log.success = false
```

测试文件 `python-agent/tests/test_mcp_policy.py` 和 `test_workflow.py` 都覆盖了 denied 行为。

### 9. MCP 调用日志如何生成

`BaseMcpClient.call_tool` 生成:

- `run_id`
- `agent_name`
- `server_name`
- `tool_name`
- `request_json`
- `response_json`
- `status`: `success`、`failed`、`denied`
- `error_message`
- `success`
- `latency_ms`

这些日志先回到 Python result，再由 GoFrame 的 `protoMcpLogs` 转为 Go model，最后 `InsertMcpCallLogs` 写 MySQL。

### 10. MCP 调用失败时如何降级

如果 transport 抛异常:

```text
except Exception as exc
-> result = {"error": {"code": "MCP_CALL_FAILED", ...}}
-> status = "failed"
-> success = false
-> 返回 McpCallResult
```

Agent 通常只看结果字段是否存在，例如 embedding 失败就没有 embedding，Milvus 就不会继续查。工作流不会因为 MCP 失败崩溃。

### FilterAgent 的 MCP 调用链

```text
FilterAgent.run
-> EmbeddingClient.embed_text
-> BaseMcpClient.call_tool("embed_text", ...)
-> MCPPolicy.check("filter", "embed_text")
-> MockMcpTransport.call 或 JsonRpcMcpTransport.call
-> 返回 {"embedding": ...}
-> BaseMcpClient._result 生成 log
-> FilterAgent 把 log 放入 result["mcp_call_logs"]
-> Python gRPC Response
-> GoFrame InsertMcpCallLogs
-> MySQL mcp_call_logs
```

## 第十部分: GoFrame Backend 讲解

### 1. `main.go` 如何启动服务

`main.go` 做这些事:

1. `ctx := gctx.GetInitCtx()` 获取 GoFrame 初始化上下文。
2. `cfg := config.Load(ctx)` 读取配置。
3. 如果命令是 `healthcheck`，只检查 Python Agent 并输出 JSON。
4. `store.New(cfg.MySQL.DSN)` 创建 MySQL store。
5. `mysqlStore.InitSchema(ctx, cfg.Schema.Path)` 初始化 schema。
6. `harness.New(cfg, mysqlStore)` 创建业务编排对象。
7. `handler.New(mysqlStore, runner)` 创建 HTTP handler。
8. `g.Server()` 创建 GoFrame server。
9. `server.SetAddr(cfg.Server.Address)` 设置监听地址。
10. `httpHandler.Register(server)` 注册路由。
11. `server.Run()` 启动服务。

### 2. controller 层负责什么

本项目 controller 对应 `internal/handler/handler.go`。

它负责:

- 注册路由。
- 解析 HTTP request。
- 做很轻的参数校验。
- 调用 harness。
- 把结果写成 JSON response。

它不直接写复杂业务逻辑。

### 3. service 层负责什么

项目没有独立 `service/` 目录。可以把 `internal/logic/harness/harness.go` 理解为 service/logic 合并层。

它负责:

- 创建 run_id。
- 记录步骤。
- 抓 RSS。
- 去重。
- 写 articles。
- 调 Python gRPC。
- 保存 posts。
- 保存 mcp_call_logs。
- 写 run_logs。
- 写 Markdown。
- 处理 feedback。

### 4. logic 层负责什么

同样在 `harness.go`。它是最核心的流程编排层，尤其是:

- `RunArticles`
- `ProcessFeedback`
- `callProcessArticles`
- `callProcessFeedback`
- `persistAgentResults`
- `writeMarkdown`

### 5. dao / model 如何对应 MySQL 表

当前没有 GoFrame 自动生成的 `dao`。本项目的 DAO 是手写的 `internal/store/mysql.go`。

对应关系:

- `model.Article` -> `articles`
- `model.Post` -> `posts`
- `model.FeedbackLog` -> `feedback_logs`
- `model.RunLog` -> `run_logs`
- `model.McpCallLog` -> `mcp_call_logs`
- `map[string]string` snapshot -> `user_profile_snapshot.snapshot_json`

### 6. `config.yaml` 如何被读取

`internal/config/config.go`:

```text
defaults()
-> 读取 CONFIG_PATH 或 manifest/config/config.yaml
-> yaml.Unmarshal 覆盖默认值
-> 环境变量覆盖
-> Normalize 填补空值
```

重要环境变量:

- `GOFRAME_HTTP_ADDR`
- `AGENT_GRPC_ADDR`
- `MYSQL_DSN`
- `OUTPUT_DIR`
- `AGENT_TIMEOUT_SECONDS`
- `AGENT_RETRY_TIMES`

### 7. gRPC client 如何连接 Python Agent

`internal/grpcclient/client.go`:

```text
grpc.DialContext(
  address,
  grpc.WithTransportCredentials(insecure.NewCredentials()),
  grpc.WithBlock(),
)
```

`WithBlock` 表示连接建立前阻塞，配合 timeout 可以快速发现 Python Agent 没启动。

### 8. `/health` 如何检查 MySQL 和 Python Agent

`Handler.Health`:

1. `h.store.Ping` 检查 MySQL。
2. `h.harness.AgentHealth` 调 Python `HealthCheck`。
3. 返回:

```json
{
  "status": "ok",
  "db": {"status": "ok"},
  "agent": {"status": "SERVING", "version": "..."}
}
```

如果 MySQL 或 Python 出错，对应子字段会是 `unavailable`，但顶层 `status` 仍是 `"ok"`。

### 9. `/runs/articles` 如何触发完整文章处理流程

`Handler.RunArticles` 直接调用 `h.harness.RunArticles`。

核心链路:

```text
RunArticles
-> fetchArticles
-> crawler.Deduplicate
-> store.InsertArticle
-> loadProfile
-> callProcessArticles
-> persistAgentResults
-> store.InsertMcpCallLogs
-> writeMarkdown
-> store.InsertRunLog
```

### 10. `/feedback` 如何触发反馈流程

`Handler.Feedback`:

1. JSON decode 到 `harness.FeedbackRequest`。
2. 检查 `post_id` 和 `feedback_text` 必填。
3. 调 `h.harness.ProcessFeedback`。

`ProcessFeedback`:

```text
InsertFeedbackLog
-> loadProfile
-> callProcessFeedback
-> InsertUserProfileSnapshot
-> InsertMcpCallLogs
-> InsertRunLog
```

### 11. `/posts` 如何查询生成结果

`Handler.ListPosts` 调 `store.ListPosts`。SQL 从 `posts` 表按 id 倒序查最近 N 条，并把 tags JSON 解析回 `[]string`。

### GoFrame 分层思想

本项目实际分层:

```text
controller: internal/handler
  -> 接 HTTP、参数校验、返回 JSON
service/logic: internal/logic/harness
  -> 业务流程编排
dao/store: internal/store
  -> SQL 读写
model: internal/model
  -> Go 数据结构
external client: internal/grpcclient, internal/crawler
  -> 调 Python / 抓 RSS
```

## 第十一部分: 数据库讲解

核心文件: `shared/sql/init.sql`。

### 1. `articles`

存原始文章:

- `article_uid`: 文章唯一 ID，有唯一索引。
- `source`: RSS 来源。
- `url`: 原文链接。
- `title`: 标题。
- `content`: 正文。
- `author`: 作者。
- `published_at`: 发布时间。
- `tags`: JSON 标签。
- `raw_json`: Go model 原始 JSON。

### 2. `posts`

存 Agent 生成的知识帖:

- `post_uid`: 生成帖唯一 ID。
- `article_uid`: 对应文章 ID。
- `title`: 标题。
- `markdown`: 生成的 Markdown 正文。
- `status`: `ready`、`check_failed`、`draft` 等。
- `tags`: JSON 标签。

### 3. `feedback_logs`

存用户反馈原始记录:

- `run_id`: 反馈运行 ID。
- `post_uid`: 被反馈的帖子。
- `article_uid`: 对应文章。
- `user_id`: 用户。
- `feedback_type`: 反馈类型。
- `rating`: 评分。
- `comment`: 反馈文本。
- `metadata`: JSON 元数据。

### 4. `run_logs`

存每次运行的状态和步骤:

- `run_id`
- `status`: `running`、`completed`、`failed`
- `input_count`
- `output_count`
- `error_message`
- `metadata`: 里面包含 steps、markdown_path、processed_count 等。
- `started_at`、`finished_at`

### 5. `user_profile_snapshot`

存用户画像快照:

- `user_id`
- `summary`: 当前代码里反馈流程存 sentiment。
- `snapshot_json`: `map<string,string>` 格式的画像。

### 6. `mcp_call_logs`

存所有 MCP 调用审计日志:

- `run_id`
- `agent_name`
- `server_name`
- `tool_name`
- `request_json`
- `response_json`
- `status`
- `error_message`
- `success`
- `latency_ms`

### 7. 一次文章处理流程会写入哪些表

可能写入:

- `articles`: 新抓到并去重后的文章。
- `posts`: Python 返回 `keep=true` 且有 `post_text` 的结果。
- `run_logs`: 运行开始、处理中、完成或失败。
- `mcp_call_logs`: FilterAgent 产生的 MCP 日志。

不会直接写:

- `feedback_logs`
- `user_profile_snapshot`

### 8. 一次反馈流程会写入哪些表

会写入:

- `feedback_logs`: 原始反馈。
- `user_profile_snapshot`: 新画像快照。
- `run_logs`: 反馈运行日志。
- `mcp_call_logs`: MemoryAgent 的 MCP 日志。

不会写:

- `articles`
- `posts`

### 9. 为什么 `user_profile_snapshot` 不直接存全部 Milvus/Neo4j 记忆

因为快照是给 GoFrame 和下一次 gRPC request 快速使用的轻量上下文。Milvus/Neo4j 代表长期、细粒度、可能很大的外部记忆；MySQL snapshot 只存“当前可传给 Agent 的用户画像摘要”。这样可以:

- 降低每次请求的数据量。
- 避免把外部记忆全量复制进 MySQL。
- 给前端/后端一个可解释、可回滚的画像版本。
- 即使 Milvus/Neo4j 不可用，也能靠最近快照继续个性化。

## 第十二部分: 端到端数据流讲解

用户调用:

```http
POST /runs/articles
```

完整调用链:

```text
用户
  |
  v
GoFrame Handler.RunArticles
  |
  v
Harness.RunArticles
  |
  +--> newRunID("articles")
  +--> writeRunLog(running)
  +--> fetchArticles
  |      |
  |      +--> RSSCrawler.Fetch
  |             |
  |             +--> mock://sample -> mockArticles
  |             +--> real URL -> gofeed.ParseURLWithContext
  |
  +--> crawler.Deduplicate
  +--> store.InsertArticle -> MySQL articles
  +--> loadProfile -> MySQL user_profile_snapshot 或 config profile
  +--> callProcessArticles
         |
         v
       gRPC ProcessArticlesRequest
         |
         v
       Python AgentService.ProcessArticles
         |
         v
       ArticleWorkflow.process_articles
         |
         v
       Filter -> Summary -> Rewrite -> Check
         |
         +--> MCP logs generated by Filter
         |
         v
       ProcessArticlesResponse
         |
         v
  +--> persistAgentResults -> MySQL posts
  +--> InsertMcpCallLogs -> MySQL mcp_call_logs
  +--> writeMarkdown -> shared/outputs/{run_id}.md
  +--> writeRunLog(completed) -> MySQL run_logs
  |
  v
HTTP JSON response
```

按步骤解释:

1. GoFrame 收到 `POST /runs/articles`，进入 `Handler.RunArticles`。
2. `Harness.RunArticles` 创建 `articles-时间-随机数` 格式的 `run_id`。
3. 写入 `run_logs`，状态为 `running`。
4. 读取配置里的 RSS source。
5. `RSSCrawler.Fetch` 抓文章。默认 `mock://sample`，返回两条 mock 文章。
6. `crawler.Deduplicate` 用 `article.ID` 去重。
7. `store.InsertArticle` 用 `INSERT IGNORE` 写入 MySQL `articles`，重复文章不会再次插入。
8. `loadProfile` 从 `user_profile_snapshot` 取最新画像，没有则用配置里的默认 profile。
9. `callProcessArticles` 构造 `ProcessArticlesRequest`。
10. `grpcclient.Client.ProcessArticles` 调 Python。
11. Python `AgentService.ProcessArticles` 把 protobuf 转 dict。
12. `ArticleWorkflow.process_articles` 标准化 state。
13. Filter Agent 打分，调用 embedding、Milvus、Neo4j，并生成 `mcp_call_logs`。
14. Summary Agent 调 LLMTool 生成摘要。
15. Rewrite Agent 调 LLMTool 生成 Markdown 正文。
16. Check Agent 做本地字段检查。
17. Python 把 `article_results` 转为 `ProcessArticlesResponse`。
18. GoFrame `persistAgentResults` 保存 `posts`。
19. GoFrame `InsertMcpCallLogs` 保存 MCP 日志。
20. GoFrame `writeMarkdown` 写 `shared/outputs/{run_id}.md`。
21. GoFrame `writeRunLog` 把 run 标为 `completed`。

数据流图:

```text
RSS source
  |
  v
model.Article
  |
  +--> MySQL articles
  |
  v
agentpb.Article
  |
  v
ProcessArticlesRequest
  |
  v
Python state["articles"]
  |
  v
state["article_results"]
  |
  +--> Filter: keep/score/issues/mcp logs
  +--> Summary: summary
  +--> Rewrite: post_text
  +--> Check: check_pass
  |
  v
ProcessArticlesResponse.results
  |
  +--> MySQL posts
  +--> MySQL mcp_call_logs
  +--> MySQL run_logs
  +--> shared/outputs/*.md
```

## 第十三部分: 反馈闭环讲解

用户调用:

```http
POST /feedback
```

请求示例:

```json
{
  "post_id": "POST_UID",
  "feedback_text": "摘要有用，希望多保留工程实践细节",
  "rating": 5
}
```

完整调用链:

```text
用户
  |
  v
GoFrame Handler.Feedback
  |
  +--> decode JSON
  +--> 校验 post_id 和 feedback_text
  |
  v
Harness.ProcessFeedback
  |
  +--> newRunID("feedback")
  +--> InsertFeedbackLog -> MySQL feedback_logs
  +--> loadProfile -> MySQL user_profile_snapshot 或默认 profile
  +--> callProcessFeedback
         |
         v
       gRPC ProcessFeedbackRequest
         |
         v
       Python AgentService.ProcessFeedback
         |
         v
       ArticleWorkflow.process_feedback
         |
         +--> FeedbackAgent.extract_feedback
         +--> MemoryAgent.update snapshot + MCP logs
         |
         v
       ProcessFeedbackResponse
  |
  +--> InsertUserProfileSnapshot -> MySQL user_profile_snapshot
  +--> InsertMcpCallLogs -> MySQL mcp_call_logs
  +--> writeFeedbackRunLog(completed) -> MySQL run_logs
  |
  v
HTTP JSON response
```

反馈闭环中的关键点:

1. GoFrame 先保存原始反馈，避免后续 Python 失败导致反馈丢失。
2. Python FeedbackAgent 把自然语言反馈转成 `sentiment` 和 `extracted_feedback`。
3. MemoryAgent 基于反馈更新 snapshot。
4. MemoryAgent 如果启用 embedding，会调用 `embed_text` 产生日志，但当前没有把向量插入 Milvus。
5. MemoryAgent 如果启用 Neo4j，会调用 `update_user_interest_graph`，当前是 mock 图更新。
6. GoFrame 保存新的 `user_profile_snapshot`。
7. 下一次 `/runs/articles` 的 `loadProfile` 会取最新 snapshot。
8. FilterAgent 会用 `interests` 等字段做关键词匹配，因此下一次推荐会受反馈影响。

## 第十四部分: 测试与调试

### 1. Python 单元测试怎么跑

```powershell
cd python-agent
python -m unittest discover -s tests
```

覆盖点:

- workflow 结构化输出。
- feedback 更新画像。
- gRPC service 调用。
- LLM mock、OpenAI 缺 key fallback、JSON repair、fallback issue。
- MCP 权限和 denied 日志。
- skills 文档必需段落。

### 2. `smoke_e2e.ps1` 怎么跑

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_e2e.ps1
```

它会启动依赖并做完整端到端验证。需要 Docker Desktop 和本机 Python/Go。

### 3. `integration_test.ps1` 怎么跑

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\integration_test.ps1
```

它会先跑 Go/Python 单元测试，再跑 E2E smoke。

### 4. 如何验证 MySQL 中是否有 posts

```powershell
docker compose exec -T mysql mysql -uroot -prootpass knowledge_post_agent -e "SELECT post_uid, article_uid, status, created_at FROM posts ORDER BY id DESC LIMIT 5;"
```

### 5. 如何验证 Markdown 是否生成

看 `/runs/articles` 返回的 `result.markdown_path`，或者列目录:

```powershell
Get-ChildItem .\shared\outputs
```

Linux/macOS:

```bash
ls -la shared/outputs
```

### 6. 如何查看 `mcp_call_logs`

```powershell
docker compose exec -T mysql mysql -uroot -prootpass knowledge_post_agent -e "SELECT run_id, agent_name, server_name, tool_name, status, success, latency_ms FROM mcp_call_logs ORDER BY id DESC LIMIT 20;"
```

### 7. 如果 Python Agent 没启动，GoFrame 会报什么

`/health` 中:

```json
"agent": {
  "status": "unavailable",
  "error": "..."
}
```

`/runs/articles` 中 `grpc_process_articles` 会 retry，最后 `result.status` 为 `failed`，常见错误是 connection refused 或 context deadline exceeded。

### 8. 如果 MySQL 没启动，会报什么

`/health` 中:

```json
"db": {
  "status": "unavailable",
  "error": "..."
}
```

`/runs/articles` 可能在 `save_articles` 阶段失败。GoFrame 启动时 `InitSchema` 也会 warning。

### 9. 如果 `LLM_PROVIDER=openai` 但没有 API key，会发生什么

`build_llm_client` 会:

1. 发现 `OPENAI_API_KEY` 为空。
2. 记录 warning: missing key，falling back to mock。
3. 返回 `MockLLMClient`。
4. 服务继续运行，不崩溃。

## 第十五部分: 按学习顺序给路线

### 第 1 天: 只看 README + 运行项目

要看的文件:

- `README.md`
- `docker-compose.yml`
- `.env.example`

要理解的问题:

- 项目是干什么的。
- 哪些是真实实现，哪些是 mock。
- HTTP API 有哪些。

要运行的命令:

```powershell
docker compose up -d mysql
cd python-agent
python server.py
cd ..\goframe-backend
go run .
```

学完后应该能回答:

- 为什么要先启动 MySQL 和 Python Agent。
- `/health` 会检查什么。

### 第 2 天: 看 proto + gRPC 调用

要看的文件:

- `shared/proto/agent.proto`
- `python-agent/app/grpc_server.py`
- `goframe-backend/internal/grpcclient/client.go`
- `goframe-backend/internal/logic/harness/harness.go` 的 `callProcessArticles`、`callProcessFeedback`

要理解的问题:

- Request/Response 字段如何映射。
- Go 怎么构造请求。
- Python 怎么实现服务。

要运行的命令:

```powershell
python python-agent\examples\client_example.py
```

学完后应该能回答:

- `ProcessArticlesRequest.articles.raw_text` 从哪里来。
- `ArticleProcessResult.mcp_call_logs` 最后写到哪里。

### 第 3 天: 看 Python Agent Workflow

要看的文件:

- `python-agent/app/workflow/graph.py`
- `python-agent/app/workflow/state.py`
- `python-agent/app/contracts.py`

要理解的问题:

- state 里有哪些字段。
- LangGraph 不存在时为什么还能跑。
- Article Workflow 和 Feedback Workflow 的入口和 END 是什么。

要运行的命令:

```powershell
cd python-agent
python -m unittest tests.test_workflow
```

学完后应该能回答:

- `article_results` 是哪个 Agent 创建的。
- `updated_profile_snapshot` 是哪个 Agent 写的。

### 第 4 天: 看各个 Agent

要看的文件:

- `python-agent/app/agents/filter_agent.py`
- `python-agent/app/agents/summary_agent.py`
- `python-agent/app/agents/rewrite_agent.py`
- `python-agent/app/agents/check_agent.py`
- `python-agent/app/agents/feedback_agent.py`
- `python-agent/app/agents/memory_agent.py`

要理解的问题:

- 每个 Agent 读写哪些 state 字段。
- 哪些 Agent 调 LLM。
- 哪些 Agent 调 MCP。

要运行的命令:

```powershell
cd python-agent
python -m unittest tests.test_workflow.ArticleWorkflowTest
```

学完后应该能回答:

- `keep` 是怎么得到的。
- `check_pass` 是怎么得到的。

### 第 5 天: 看 LLM Tool 和 Skill

要看的文件:

- `python-agent/app/tools/llm_tool.py`
- `python-agent/app/skill_loader.py`
- `python-agent/app/skills/summary_skill.md`
- `python-agent/app/skills/rewrite_post_skill.md`
- `python-agent/app/skills/feedback_extract_skill.md`

要理解的问题:

- provider 如何选择。
- Pydantic 如何校验结构化输出。
- repair 和 fallback 如何保证稳定性。

要运行的命令:

```powershell
cd python-agent
python -m unittest tests.test_llm_tool tests.test_skills
```

学完后应该能回答:

- OpenAI 缺 API key 为什么不会崩。
- mock LLM 如何生成摘要和推文。

### 第 6 天: 看 MCP Client 和 Policy

要看的文件:

- `python-agent/app/mcp/base_client.py`
- `python-agent/app/mcp/policy.py`
- `python-agent/app/mcp/embedding_client.py`
- `python-agent/app/mcp/milvus_client.py`
- `python-agent/app/mcp/neo4j_client.py`
- `python-agent/app/mcp/fetch_client.py`

要理解的问题:

- 权限如何校验。
- denied 和 failed 有什么区别。
- MCP 日志如何生成。

要运行的命令:

```powershell
cd python-agent
python -m unittest tests.test_mcp_policy
```

学完后应该能回答:

- 为什么 FilterAgent 调 fetch 会被拒绝。
- `MOCK_MCP=false` 时调用路径有什么变化。

### 第 7 天: 看 GoFrame Backend

要看的文件:

- `goframe-backend/main.go`
- `goframe-backend/internal/handler/handler.go`
- `goframe-backend/internal/logic/harness/harness.go`
- `goframe-backend/internal/store/mysql.go`
- `goframe-backend/internal/crawler/rss.go`

要理解的问题:

- HTTP API 如何进入业务流程。
- GoFrame 分层如何落在这个项目里。
- MySQL 写入发生在哪些函数。

要运行的命令:

```powershell
cd goframe-backend
go test ./...
go run .
```

学完后应该能回答:

- `/runs/articles` 里每一步对应哪个函数。
- `/feedback` 为什么先写 feedback_logs。

### 第 8 天: 看数据库和日志

要看的文件:

- `shared/sql/init.sql`
- `goframe-backend/internal/store/mysql.go`
- `goframe-backend/internal/model/model.go`

要理解的问题:

- 每张表存什么。
- run_logs metadata 里有什么。
- mcp_call_logs 如何审计工具调用。

要运行的命令:

```powershell
docker compose exec -T mysql mysql -uroot -prootpass knowledge_post_agent -e "SHOW TABLES;"
docker compose exec -T mysql mysql -uroot -prootpass knowledge_post_agent -e "SELECT * FROM run_logs ORDER BY id DESC LIMIT 3\G"
```

学完后应该能回答:

- 一次文章处理会写哪些表。
- 一次反馈处理会写哪些表。

### 第 9 天: 跑 E2E Smoke

要看的文件:

- `scripts/smoke_e2e.ps1`

要理解的问题:

- 脚本启动了哪些服务。
- 它验证了哪些条件。

要运行的命令:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_e2e.ps1
```

学完后应该能回答:

- `MOCK_MCP=false` 为什么需要启动 4 个 MCP server。
- 如何确认 Markdown、posts、run_logs、mcp_call_logs 都生成了。

### 第 10 天: 尝试改一个小功能

建议小功能:

- 在 `CheckAgent` 里增加一个简单规则: 如果 `post_text` 太短，追加 `post_too_short`。
- 或在 `FilterAgent._score_article` 里处理 `negative_preferences`，命中负面偏好时降分。

要看的文件:

- `python-agent/app/agents/check_agent.py` 或 `filter_agent.py`
- `python-agent/tests/test_workflow.py`

要理解的问题:

- 修改 state 的哪个字段。
- 如何补测试。
- 是否影响 gRPC response 和 GoFrame 保存。

要运行的命令:

```powershell
cd python-agent
python -m unittest discover -s tests
```

学完后应该能回答:

- 怎么安全扩展一个 Agent。
- 怎么判断改动没有破坏 E2E 流程。

## 第十六部分: 面试讲法

### 1. 项目背景

KnowMate 是一个个性化知识文章处理系统。它从 RSS 抓取候选文章，通过 Agent Workflow 做筛选、总结、改写和校验，再把生成的知识帖保存到 MySQL 并输出 Markdown。同时它支持用户反馈闭环，能把反馈更新成用户画像，影响后续推荐。

### 2. 技术架构

整体是 GoFrame + Python Agent Service 的双服务架构。GoFrame 负责 HTTP API、RSS、MySQL 和 Markdown；Python 通过 gRPC 提供 Agent 能力；Agent 内部用 LangGraph 编排；外部能力通过 MCP-style client 访问；MySQL 存业务数据、运行日志和用户画像快照；Milvus/Neo4j 当前用 mock server 模拟。

### 3. 我的职责

可以这样说:

我负责搭建 MVP 的端到端链路，包括 GoFrame HTTP API、MySQL 表结构、Go 到 Python 的 gRPC 契约、Python Agent Workflow、LLM 结构化输出、MCP 权限和调用日志，以及 E2E smoke 脚本。重点是让系统先可运行、可观测、可扩展。

### 4. 核心难点

核心难点不是单个模型调用，而是跨语言、跨服务的数据契约和可观测性:

- proto 字段要同时服务 Go 和 Python。
- Agent 输出必须结构化，否则 GoFrame 无法稳定落库。
- MCP 调用需要权限控制和审计日志。
- LLM/MCP 失败不能拖垮整个 workflow。
- 用户反馈要能沉淀成下一次可使用的画像快照。

### 5. 如何使用 LangGraph

在 `python-agent/app/workflow/graph.py` 中，我用 `StateGraph(AgentState)` 建图。文章流程是 `filter -> summary -> rewrite -> check -> END`，反馈流程是 `feedback -> memory -> END`。每个节点都是 Agent 的 `run(state)` 函数。为了提高 MVP 可运行性，如果没有安装 LangGraph，会自动 fallback 到顺序执行。

### 6. 如何使用 gRPC

共享契约在 `shared/proto/agent.proto`。它定义了 `HealthCheck`、`ProcessArticles`、`ProcessFeedback` 三个 RPC。GoFrame 使用生成的 `agentpb` client 构造请求，Python 使用 `agent_pb2_grpc.AgentServiceServicer` 实现服务。这样 Go 和 Python 之间不用传随意 JSON，而是用强契约消息。

### 7. 如何使用 MCP

MCP 这里采用 MCP-style JSON-RPC 形态。Python Agent 里的 `BaseMcpClient` 统一做权限检查、调用 transport、记录 request/response 和 latency。默认用 `MockMcpTransport`，也可以设置 `MOCK_MCP=false` 调独立的 HTTP mock servers。所有 MCP 日志最后写入 MySQL `mcp_call_logs`。

### 8. 如何实现长期记忆

当前 MVP 中长期记忆分两层: MySQL 存 `user_profile_snapshot`，代表轻量、可传给下一次请求的用户画像；Milvus/Neo4j 用 mock server 表示未来的向量记忆和兴趣图谱。反馈流程会通过 MemoryAgent 更新 snapshot，并 mock 更新 Neo4j interest graph。

### 9. 如何实现用户反馈闭环

用户调用 `/feedback` 后，GoFrame 先写 `feedback_logs`，再调用 Python `ProcessFeedback`。FeedbackAgent 抽取 `sentiment` 和 `extracted_feedback`，MemoryAgent 更新 `updated_profile_snapshot` 并记录 MCP 日志。GoFrame 保存新的 `user_profile_snapshot`。下一次 `/runs/articles` 会读取最新 snapshot，FilterAgent 根据兴趣关键词和图信号调整打分。

### 10. 如何保证系统稳定性

稳定性来自几层降级:

- LLM 输出用 Pydantic 校验。
- JSON 解析失败会 repair 一次。
- repair 失败会 fallback 到 mock/template 输出。
- MCP 权限拒绝和调用失败都变成结构化 log，不让 workflow 崩溃。
- GoFrame 调 Python 有 timeout 和 retry。
- run_logs 记录每一步状态，方便排查。

### 11. 项目目前的不足

- LLM 默认 mock，真实 OpenAI 只实现了兼容 chat completions，Claude 还是 stub。
- Milvus/Neo4j 是 mock，不是真实持久化服务。
- CheckAgent 当前只做字段检查，没有真正事实检查、URL 检查或语义去重。
- FeedbackAgent 当前没有调用 MCP 搜索历史反馈。
- MemoryAgent 当前没有把 feedback embedding 写入 Milvus。
- `mcp_policy.mock_transport` 字段还没有真正参与运行时 transport 选择。
- GoFrame 还没有拆出标准 GoFrame dao/service，多数编排集中在 `harness.go`。

### 12. 后续优化方向

- 接入真实 OpenAI/Claude，并增加模型超时、重试和成本统计。
- 接入真实 Milvus 和 Neo4j，把 mock memory 变成持久化长期记忆。
- 增强 CheckAgent: URL alive、事实一致性、重复推荐检测。
- 让 request 级 `mcp_policy.mock_transport` 真正影响 transport 或明确移除该字段。
- 增加用户维度和权限体系，支持多用户画像。
- 增加异步任务队列，避免 `/runs/articles` 长时间阻塞 HTTP 请求。
- 增加可视化 run trace，把每个 Agent 输入输出、MCP 日志和 LLM fallback 展示出来。
- 给 GoFrame 按更标准的 controller/service/logic/dao 分层拆分 harness。
