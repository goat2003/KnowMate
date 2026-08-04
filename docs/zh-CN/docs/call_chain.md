# KnowMate 完整调用链分析

> 原文镜像：`docs/call_chain.md`
>
> 原文件已以中文为主；本镜像保留命令、路径、代码块和协议字段原样。


> 本文只分析当前代码中的实际调用链，不改业务代码。  
> 重点链路: `POST /runs/articles` 文章处理链路、`POST /feedback` 反馈更新链路。  
> 当前项目是 MVP: GoFrame、MySQL、gRPC、Python Workflow、Markdown 输出是真实链路；LLM 默认 mock；MCP 默认进程内 mock，也可以通过 HTTP JSON-RPC 调独立 mock servers；Milvus/Neo4j 当前不是生产级真实服务，而是 mock/内存模拟。

## 一、核心文件地图

| 层 | 文件 | 关键函数/类 | 作用 |
|---|---|---|---|
| HTTP controller | `goframe-backend/internal/handler/handler.go` | `Register`、`RunArticles`、`Feedback` | 注册路由，接收 HTTP 请求，调用业务编排 |
| Go 业务编排 | `goframe-backend/internal/logic/harness/harness.go` | `RunArticles`、`ProcessFeedback` | 两条主链路的 Go 侧总控 |
| RSS | `goframe-backend/internal/crawler/rss.go` | `RSSCrawler.Fetch`、`Deduplicate` | 抓取 RSS 或生成 mock 文章，并去重 |
| MySQL | `goframe-backend/internal/store/mysql.go` | `InsertArticle`、`InsertPost`、`InsertFeedbackLog`、`InsertUserProfileSnapshot`、`InsertMcpCallLogs`、`InsertRunLog` | 写入业务表和日志表 |
| Go gRPC client | `goframe-backend/internal/grpcclient/client.go` | `ProcessArticles`、`ProcessFeedback` | 调用 Python Agent gRPC |
| gRPC contract | `shared/proto/agent.proto` | `AgentService`、`ProcessArticlesRequest`、`ProcessFeedbackRequest` | Go/Python 共享协议 |
| Python gRPC server | `python-agent/app/grpc_server.py` | `AgentService.ProcessArticles`、`AgentService.ProcessFeedback` | 接收 gRPC，转成 Python dict，调用 workflow |
| Workflow | `python-agent/app/workflow/graph.py` | `ArticleWorkflow.process_articles`、`ArticleWorkflow.process_feedback` | 组织 LangGraph 或 sequential fallback |
| Article Agents | `python-agent/app/agents/*.py` | `FilterAgent`、`SummaryAgent`、`RewriteAgent`、`CheckAgent` | 文章筛选、摘要、改写、检查 |
| Feedback Agents | `python-agent/app/agents/*.py` | `FeedbackAgent`、`MemoryAgent` | 反馈抽取、画像更新 |
| LLM | `python-agent/app/tools/llm_tool.py` | `LLMTool.summarize`、`rewrite_post`、`extract_feedback` | mock/openai/claude stub、结构化输出、repair、fallback |
| MCP | `python-agent/app/mcp/*.py` | `BaseMcpClient.call_tool`、`EmbeddingClient`、`MilvusClient`、`Neo4jClient` | 工具调用、权限、日志、mock/JSON-RPC transport |

## 二、文章处理链路: `POST /runs/articles`

### 2.1 总调用链图

```text
POST /runs/articles
  |
  v
goframe-backend/internal/handler/handler.go
Handler.RunArticles
  |
  v
goframe-backend/internal/logic/harness/harness.go
Harness.RunArticles
  |
  +--> writeRunLog(running) -> MySQL run_logs
  |
  +--> fetchArticles
  |      |
  |      v
  |   goframe-backend/internal/crawler/rss.go
  |   RSSCrawler.Fetch
  |      |
  |      +--> mock://sample -> mockArticles
  |      +--> real RSS URL -> gofeed.ParseURLWithContext
  |
  +--> crawler.Deduplicate
  |
  +--> Store.InsertArticle -> MySQL articles
  |
  +--> loadProfile -> MySQL user_profile_snapshot 或 config default profile
  |
  +--> callProcessArticles
         |
         v
      grpcclient.Client.ProcessArticles
         |
         v
      Python gRPC AgentService.ProcessArticles
         |
         v
      ArticleWorkflow.process_articles
         |
         v
      FilterAgent.run
         |
         +--> MCP: Neo4jClient.get_profile_context
         +--> MCP: EmbeddingClient.embed_text
         +--> MCP: MilvusClient.search_similar_memory
         |
         v
      SummaryAgent.run
         |
         +--> LLMTool.summarize
         |
         v
      RewriteAgent.run
         |
         +--> LLMTool.rewrite_post
         |
         v
      CheckAgent.run
         |
         v
      ProcessArticlesResponse
         |
         v
Harness.persistAgentResults
  |
  +--> Store.InsertPost -> MySQL posts
  +--> Store.InsertMcpCallLogs -> MySQL mcp_call_logs
  +--> writeMarkdown -> shared/outputs/{run_id}.md
  +--> writeRunLog(completed/failed) -> MySQL run_logs
  |
  v
HTTP JSON response
```

### 2.2 每一步输入、输出、数据结构变化

| 步骤 | 文件/函数 | 输入 | 输出 | 数据结构变化 | 写 MySQL | LLM | MCP | mock 点 |
|---|---|---|---|---|---|---|---|---|
| 1. 路由注册 | `handler.go` `Handler.Register` | GoFrame server | 注册 `/runs/articles` | 无业务数据变化 | 否 | 否 | 否 | 否 |
| 2. HTTP controller | `handler.go` `Handler.RunArticles` | `*ghttp.Request` | JSON `{ok, result}` | HTTP request 转成调用 `Harness.RunArticles`，本接口没有请求 body | 否 | 否 | 否 | 否 |
| 3. 创建 run | `harness.go` `Harness.RunArticles` | `context.Context` | `RunArticlesResult{RunID, Status, Steps...}` | 生成 `articles-{time}-{random}` 格式 run_id，初始化步骤日志 | 是，`run_logs` running | 否 | 否 | 否 |
| 4. 读取 RSS sources | `harness.go` `fetchArticles` | `cfg.RSS.Sources` | `[]model.Article`、source 数量 | 遍历 enabled source，调用 crawler | 否 | 否 | 否 | 默认配置 source 是 `mock://sample` |
| 5. RSS fetch | `rss.go` `RSSCrawler.Fetch` | `config.RSSSource` | `[]model.Article` | RSS item 或 mock seed 转成 Go `model.Article` | 否 | 否 | 否 | `mock://` 走 `mockArticles`；真实 URL 走 `gofeed` |
| 6. 去重 | `rss.go` `Deduplicate` | `[]model.Article` | 去重后的 `[]model.Article` | 用 `article.ID` 做 key，缺 ID 时根据 URL/title 生成稳定 ID | 否 | 否 | 否 | 否 |
| 7. 写 articles | `mysql.go` `Store.InsertArticle` | `model.Article` | `inserted bool` | `Tags` 和原始 article marshal 成 JSON，写入 SQL | 是，`articles` | 否 | 否 | `INSERT IGNORE` 让重复文章跳过 |
| 8. 读取画像 | `harness.go` `loadProfile` | `user_id` 配置 | `map[string]string` | 从 `user_profile_snapshot` 取最新快照；缺字段用 config 默认值补齐 | 读 MySQL | 否 | 否 | 无快照时使用 config 默认 profile |
| 9. 构造 gRPC request | `harness.go` `callProcessArticles`、`toProtoArticles` | `runID`、`[]model.Article`、profile | `agentpb.ProcessArticlesRequest` | `model.Article` 转 `agentpb.Article`，`Content` 变 `RawText`，profile 变 `map<string,string>` | 否 | 否 | 否 | `defaultMcpPolicy` 默认 `EnableFetch=false` |
| 10. Go gRPC 调用 | `grpcclient/client.go` `Client.ProcessArticles` | `*agentpb.ProcessArticlesRequest` | `*agentpb.ProcessArticlesResponse` | protobuf 经 gRPC 发送到 Python | 否 | 否 | 否 | 否 |
| 11. Python gRPC 接收 | `grpc_server.py` `AgentService.ProcessArticles` | protobuf request | Python dict request | `agent_pb2.Article` 转 dict: `article_id/url/title/raw_text/source/published_at/tags` | 否 | 否 | 否 | 否 |
| 12. Workflow state 初始化 | `graph.py` `ArticleWorkflow.process_articles` | dict request | `state` | `normalize_article` 标准化文章；`default_mcp_policy` 合并 MCP 开关 | 否 | 否 | 否 | transport 由启动配置 `MOCK_MCP` 决定，不由 request 的 `mock_transport` 决定 |
| 13. Filter | `filter_agent.py` `FilterAgent.run` | `state["articles"]`、profile、policy | `state["article_results"]` | 每篇文章变成 result: `{article, article_id, keep, score, summary:"", post_text:"", check_pass:false, issues, mcp_call_logs}` | 否 | 否 | 是 | Neo4j/Milvus/embedding 默认 mock |
| 14. Summary | `summary_agent.py` `SummaryAgent.run` | `article_results` 中 `keep=true` 的文章、profile、skill | result 增加 `summary` | `LLMTool.summarize` 返回 `SummaryLLMOutput`，写入 `result["summary"]` | 否 | 是 | 否 | LLM 默认 mock |
| 15. Rewrite | `rewrite_agent.py` `RewriteAgent.run` | article、summary、skill | result 增加 `post_text` | `LLMTool.rewrite_post` 返回 `RewriteLLMOutput`，写入 Markdown 正文 | 否 | 是 | 否 | LLM 默认 mock |
| 16. Check | `check_agent.py` `CheckAgent.run` | result、article | result 增加/更新 `check_pass`、`issues` | 本地检查 summary/post_text/url 是否存在 | 否 | 否 | 否 | 当前不做真实事实检查，也不调 URL/Milvus |
| 17. Python response | `graph.py` `process_articles` + `grpc_server.py` | `state["article_results"]` | `ProcessArticlesResponse` | Python dict result 转 `agent_pb2.ArticleProcessResult` | 否 | 否 | 否 | 否 |
| 18. 保存 posts | `harness.go` `persistAgentResults`、`mysql.go` `InsertPost` | gRPC results | `[]model.Post` | `ArticleProcessResult` 转 `model.Post`，`post_text` 写入 `Markdown`，`check_pass=false` 则 status=`check_failed` | 是，`posts` | 否 | 否 | 否 |
| 19. 保存 MCP logs | `harness.go` `protoMcpLogs`、`mysql.go` `InsertMcpCallLogs` | response 中的 `McpCallLog` | MySQL rows | protobuf log 转 Go `model.McpCallLog`，JSON 字符串规范化后入库 | 是，`mcp_call_logs` | 否 | 否 | MCP 成功/失败/拒绝都会记录 |
| 20. Markdown 输出 | `harness.go` `writeMarkdown` | `runID`、`[]model.Post` | `shared/outputs/{run_id}.md` | 多个 post 拼成一个 Markdown 文件，带 run_id 和 post 注释 | 否 | 否 | 否 | 否 |
| 21. 完成日志 | `harness.go` `writeRunLog` | `RunArticlesResult` | run log row 更新 | metadata 包含 steps、markdown_path、processed_count 等 | 是，`run_logs` | 否 | 否 | 否 |

### 2.3 文章链路中的数据结构演化

#### HTTP 层

`POST /runs/articles` 当前没有解析请求 body。输入主要来自配置:

```text
goframe-backend/manifest/config/config.yaml
-> rss.sources
-> crawler limits
-> profile default
-> agent grpc address
-> output dir
```

Controller 输出:

```json
{
  "ok": true,
  "result": {
    "run_id": "articles-...",
    "status": "completed",
    "candidate_count": 2,
    "new_articles": 2,
    "processed_count": 2,
    "posts_saved": 2,
    "markdown_path": ".../shared/outputs/articles-....md",
    "steps": []
  }
}
```

#### Go RSS 模型: `model.Article`

来源: `rss.go` `RSSCrawler.Fetch`。

```go
type Article struct {
    ID          string
    URL         string
    Title       string
    Content     string
    Author      string
    PublishedAt string
    Source      string
    Tags        []string
    CreatedAt   time.Time
}
```

写 MySQL `articles` 时:

- `ID` -> `article_uid`
- `Source` -> `source`
- `URL` -> `url`
- `Title` -> `title`
- `Content` -> `content`
- `Tags` -> JSON `tags`
- 整个 article -> JSON `raw_json`

#### gRPC request: `agentpb.ProcessArticlesRequest`

来源: `harness.go` `callProcessArticles`。

```text
ProcessArticlesRequest
├── run_id
├── articles[]: Article
│   ├── article_id = model.Article.ID
│   ├── url = model.Article.URL
│   ├── title = model.Article.Title
│   ├── raw_text = model.Article.Content
│   ├── source = model.Article.Source
│   ├── published_at = model.Article.PublishedAt
│   └── tags = model.Article.Tags
├── user_profile_snapshot: map<string,string>
└── mcp_policy
```

#### Python workflow state

来源: `ArticleWorkflow.process_articles`。

```python
state = {
    "run_id": "...",
    "articles": [normalize_article(article), ...],
    "user_profile_snapshot": {...},
    "mcp_policy": {...},
}
```

Filter 后变为:

```python
state["article_results"] = [
    {
        "article": {...},
        "article_id": "...",
        "keep": True,
        "score": 0.95,
        "summary": "",
        "post_text": "",
        "check_pass": False,
        "issues": [],
        "mcp_call_logs": [...],
        "filter_reasons": [...]
    }
]
```

Summary 后:

```python
result["summary"] = "这篇文章..."
```

Rewrite 后:

```python
result["post_text"] = "【知识笔记】...\n\n原文: ..."
```

Check 后:

```python
result["check_pass"] = True
result["issues"] = []
```

#### gRPC response: `ProcessArticlesResponse`

Python 返回:

```text
ProcessArticlesResponse
├── run_id
└── results[]
    ├── article_id
    ├── keep
    ├── score
    ├── summary
    ├── post_text
    ├── check_pass
    ├── issues[]
    └── mcp_call_logs[]
```

#### Go 保存模型: `model.Post`

来源: `harness.go` `persistAgentResults`。

```go
post := model.Post{
    PostUID:    stablePostID(runID, item.ArticleId),
    ArticleUID: item.ArticleId,
    Title:      article.Title,
    Markdown:   item.PostText,
    Status:     "ready" 或 "check_failed",
    Tags:       article.Tags,
}
```

写入 MySQL `posts`，再由 `writeMarkdown` 输出到 `shared/outputs/{run_id}.md`。

### 2.4 文章链路中哪里调用 LLM

当前文章链路只有两个 Agent 调 LLM:

```text
SummaryAgent.run
-> LLMTool.summarize
-> LLMTool._generate_structured
-> provider.complete_json
-> Pydantic SummaryLLMOutput
```

```text
RewriteAgent.run
-> LLMTool.rewrite_post
-> LLMTool._generate_structured
-> provider.complete_json
-> Pydantic RewriteLLMOutput
```

Provider 选择在 `python-agent/app/tools/llm_tool.py`:

- 默认 `mock`: `MockLLMClient`。
- `openai`: OpenAI-compatible `/chat/completions`，缺 API key 会 fallback 到 mock。
- `claude`: 当前是 stub，保留接口但未实现真实调用。

### 2.5 文章链路中哪里调用 MCP

实际代码里，文章链路的 MCP 调用主要在 `FilterAgent.run`:

```text
FilterAgent
-> Neo4jClient.get_profile_context
   -> BaseMcpClient.call_tool("query_user_interest_graph")

FilterAgent
-> EmbeddingClient.embed_text
   -> BaseMcpClient.call_tool("embed_text")

FilterAgent
-> MilvusClient.search_similar_memory
   -> BaseMcpClient.call_tool("search_similar_memory")
```

有一个特殊分支:

```text
if enable_fetch and raw_text empty:
    FetchClient.fetch_url -> call_tool("fetch_webpage")
```

但默认 Go 侧 `defaultMcpPolicy()` 设置 `EnableFetch=false`，所以正常链路不会走 fetch。即使手动打开，`MCPPolicy` 中 `filter` 不允许 `fetch_webpage`，会得到 `status=denied` 的 MCP 日志，而不会真正调用 transport。

当前 `SummaryAgent`、`RewriteAgent`、`CheckAgent` 不调用 MCP。`fact_check_skill.md` 设计了 URL 检查和去重，但 `CheckAgent.run` 目前只做本地字段检查。

### 2.6 文章链路中哪里写 MySQL

| 表 | 文件/函数 | 写入内容 |
|---|---|---|
| `run_logs` | `harness.go` `writeRunLog` -> `mysql.go` `InsertRunLog` | run 状态、输入输出数量、steps、markdown_path |
| `articles` | `mysql.go` `InsertArticle` | RSS 抓到的新文章 |
| `posts` | `mysql.go` `InsertPost` | Agent 生成的 Markdown post |
| `mcp_call_logs` | `mysql.go` `InsertMcpCallLogs` | FilterAgent 产生的 MCP 调用日志 |

### 2.7 文章链路中的 mock 点

| mock 点 | 位置 | 当前行为 |
|---|---|---|
| RSS mock | `rss.go` `RSSCrawler.Fetch` | URL 以 `mock://` 开头时返回 `mockArticles` 的固定文章 |
| LLM mock | `llm_tool.py` `MockLLMClient` | 默认 provider，生成模板摘要、模板推文 |
| MCP transport mock | `base_client.py` `MockMcpTransport` | `MOCK_MCP=true` 时不走 HTTP，直接返回 mock embedding/topics/matches |
| MCP HTTP mock servers | `mcp-servers/*/server.py` | `MOCK_MCP=false` 时通过 HTTP JSON-RPC 调用这些 mock server |
| Milvus mock | `mcp-servers/milvus-mcp/server.py` 或 `MockMcpTransport` | 内存向量/固定相似结果，不是真实 Milvus |
| Neo4j mock | `mcp-servers/neo4j-mcp/server.py` 或 `MockMcpTransport` | 内存用户兴趣图，不是真实 Neo4j |
| Check mock/简化 | `check_agent.py` | 不是外部 mock，但当前只是字段校验，没有真实事实核查 |

## 三、反馈更新链路: `POST /feedback`

### 3.1 总调用链图

```text
POST /feedback
  |
  v
goframe-backend/internal/handler/handler.go
Handler.Feedback
  |
  +--> decodeJSON -> harness.FeedbackRequest
  +--> 校验 post_id / feedback_text
  |
  v
goframe-backend/internal/logic/harness/harness.go
Harness.ProcessFeedback
  |
  +--> writeFeedbackRunLog(running) -> MySQL run_logs
  |
  +--> Store.InsertFeedbackLog -> MySQL feedback_logs
  |
  +--> loadProfile -> MySQL user_profile_snapshot 或 config default profile
  |
  +--> callProcessFeedback
         |
         v
      grpcclient.Client.ProcessFeedback
         |
         v
      Python gRPC AgentService.ProcessFeedback
         |
         v
      ArticleWorkflow.process_feedback
         |
         v
      FeedbackAgent.run
         |
         +--> LLMTool.extract_feedback
         |
         v
      MemoryAgent.run
         |
         +--> MCP: EmbeddingClient.embed_text
         +--> MCP: Neo4jClient.update_profile
         |
         v
      ProcessFeedbackResponse
         |
         v
Harness.ProcessFeedback
  |
  +--> Store.InsertUserProfileSnapshot -> MySQL user_profile_snapshot
  +--> Store.InsertMcpCallLogs -> MySQL mcp_call_logs
  +--> writeFeedbackRunLog(completed/failed) -> MySQL run_logs
  |
  v
HTTP JSON response
```

### 3.2 每一步输入、输出、数据结构变化

| 步骤 | 文件/函数 | 输入 | 输出 | 数据结构变化 | 写 MySQL | LLM | MCP | mock 点 |
|---|---|---|---|---|---|---|---|---|
| 1. 路由注册 | `handler.go` `Handler.Register` | GoFrame server | 注册 `/feedback` | 无业务数据变化 | 否 | 否 | 否 | 否 |
| 2. HTTP controller | `handler.go` `Handler.Feedback` | JSON body | `harness.FeedbackRequest` | 解析 `post_id/article_id/user_id/feedback_text/feedback_type/rating`，校验 `post_id` 和 `feedback_text` | 否 | 否 | 否 | 否 |
| 3. 创建反馈 run | `harness.go` `ProcessFeedback` | `FeedbackRequest` | `FeedbackResult{RunID, Status}` | 生成 `feedback-{time}-{random}` run_id，默认 `FeedbackType=text` | 是，`run_logs` running | 否 | 否 | 否 |
| 4. 写 feedback_logs | `mysql.go` `InsertFeedbackLog` | `model.FeedbackLog` | SQL row | HTTP 反馈转成数据库原始反馈记录 | 是，`feedback_logs` | 否 | 否 | 否 |
| 5. 读取画像 | `harness.go` `loadProfile` | user_id 配置 | `map[string]string` | 从 `user_profile_snapshot` 取最新画像；缺省使用 config profile | 读 MySQL | 否 | 否 | 无快照时使用默认 profile |
| 6. 构造 gRPC request | `harness.go` `callProcessFeedback` | `runID`、`userID`、`FeedbackRequest`、profile | `agentpb.ProcessFeedbackRequest` | `FeedbackRequest` 转 `agentpb.FeedbackItem`，profile 转 map | 否 | 否 | 否 | `defaultMcpPolicy` 默认 enable_embedding/milvus/neo4j |
| 7. Go gRPC 调用 | `grpcclient/client.go` `Client.ProcessFeedback` | `*agentpb.ProcessFeedbackRequest` | `*agentpb.ProcessFeedbackResponse` | protobuf 经 gRPC 发送到 Python | 否 | 否 | 否 | 否 |
| 8. Python gRPC 接收 | `grpc_server.py` `AgentService.ProcessFeedback` | protobuf request | Python dict request | `FeedbackItem` 转 dict，metadata 转 dict | 否 | 否 | 否 | 否 |
| 9. Workflow state 初始化 | `graph.py` `ArticleWorkflow.process_feedback` | dict request | `state` | 初始化 `run_id`、`feedback`、`user_profile_snapshot`、`mcp_policy`、`mcp_call_logs=[]` | 否 | 否 | 否 | transport 由 `MOCK_MCP` 决定 |
| 10. FeedbackAgent | `feedback_agent.py` `FeedbackAgent.run` | `state["feedback"]`、skill | `sentiment`、`extracted_feedback` | LLM 输出转结构化反馈信号 | 否 | 是 | 否 | LLM 默认 mock |
| 11. MemoryAgent | `memory_agent.py` `MemoryAgent.run` | snapshot、sentiment、extracted_feedback、mcp_policy | `updated_profile_snapshot`、`mcp_call_logs` | 更新画像字段: `last_feedback_sentiment`、`feedback_count`、`latest_feedback` | 否 | 否 | 是 | embedding/Neo4j 默认 mock |
| 12. Python response | `graph.py` + `grpc_server.py` | workflow result | `ProcessFeedbackResponse` | dict 转 protobuf response | 否 | 否 | 否 | 否 |
| 13. 保存画像快照 | `mysql.go` `InsertUserProfileSnapshot` | userID、updated snapshot、sentiment | SQL row | `map[string]string` marshal 成 JSON 写入 `snapshot_json` | 是，`user_profile_snapshot` | 否 | 否 | 否 |
| 14. 保存 MCP logs | `mysql.go` `InsertMcpCallLogs` | response.McpCallLogs | SQL rows | MCP logs 转 MySQL 审计记录 | 是，`mcp_call_logs` | 否 | 否 | 包括 mock MCP 调用日志 |
| 15. 完成日志 | `harness.go` `writeFeedbackRunLog` | `FeedbackResult` | run log row 更新 | metadata 记录 sentiment 和 steps | 是，`run_logs` | 否 | 否 | 否 |

### 3.3 反馈链路中的数据结构演化

#### HTTP request body

`handler.go` `Feedback` 解析为:

```go
type FeedbackRequest struct {
    PostID       string `json:"post_id"`
    ArticleID    string `json:"article_id"`
    UserID       string `json:"user_id"`
    FeedbackText string `json:"feedback_text"`
    FeedbackType string `json:"feedback_type"`
    Rating       int    `json:"rating"`
}
```

必填校验:

```text
post_id != ""
feedback_text != ""
```

#### MySQL 原始反馈: `feedback_logs`

`ProcessFeedback` 先把请求写入 `model.FeedbackLog`:

```go
model.FeedbackLog{
    RunID:        result.RunID,
    PostUID:      req.PostID,
    ArticleUID:   req.ArticleID,
    UserID:       userID,
    FeedbackType: req.FeedbackType,
    Rating:       req.Rating,
    Comment:      req.FeedbackText,
    Metadata:     map[string]any{"source": "api"},
}
```

这一步先落库，保证即使 Python Agent 失败，原始反馈也不会丢。

#### gRPC request: `ProcessFeedbackRequest`

`callProcessFeedback` 构造:

```text
ProcessFeedbackRequest
├── run_id
├── feedback[]
│   ├── feedback_id = runID + "-item"
│   ├── user_id
│   ├── article_id
│   ├── post_id
│   ├── feedback_text
│   ├── feedback_type
│   ├── rating
│   └── metadata = {"source": "goframe-backend"}
├── user_profile_snapshot
└── mcp_policy
```

#### Python workflow state

`ArticleWorkflow.process_feedback` 初始化:

```python
state = {
    "run_id": "...",
    "feedback": [...],
    "user_profile_snapshot": {...},
    "mcp_policy": {...},
    "mcp_call_logs": [],
}
```

FeedbackAgent 后:

```python
state["sentiment"] = "positive" | "neutral" | "negative"
state["extracted_feedback"] = [
    "摘要有用，希望多保留工程实践细节"
]
```

MemoryAgent 后:

```python
state["updated_profile_snapshot"] = {
    ...原 snapshot,
    "last_feedback_sentiment": "positive",
    "feedback_count": "2",
    "latest_feedback": "摘要有用，希望多保留工程实践细节"
}
state["mcp_call_logs"] = [...]
```

#### gRPC response: `ProcessFeedbackResponse`

返回给 Go:

```text
ProcessFeedbackResponse
├── run_id
├── sentiment
├── extracted_feedback[]
├── updated_profile_snapshot: map<string,string>
└── mcp_call_logs[]
```

#### MySQL 用户画像快照

`InsertUserProfileSnapshot` 写:

```text
user_id = userID
summary = response.Sentiment
snapshot_json = JSON(response.UpdatedProfileSnapshot)
```

下一次文章处理时，`loadProfile` 会读取这个最新 snapshot，传给 `ProcessArticlesRequest.user_profile_snapshot`，从而影响 FilterAgent 的关键词匹配和图上下文。

### 3.4 反馈链路中哪里调用 LLM

当前反馈链路只有 `FeedbackAgent` 调 LLM:

```text
FeedbackAgent.run
-> LLMTool.extract_feedback
-> LLMTool._generate_structured
-> provider.complete_json
-> Pydantic FeedbackLLMOutput
```

输出字段:

- `sentiment`: `positive`、`neutral`、`negative`
- `extracted_feedback`: 结构化偏好信号或反馈文本摘要
- `issues`: LLM 解析失败、fallback 等问题

LLM 默认是 `MockLLMClient`:

- rating >= 4 更可能 positive。
- rating <= 2 更可能 negative。
- 文本含“有用/喜欢/good”等更可能 positive。
- 文本含“差/不喜欢/没用/bad”等更可能 negative。

### 3.5 反馈链路中哪里调用 MCP

当前反馈链路 MCP 调用在 `MemoryAgent.run`:

```text
MemoryAgent
-> EmbeddingClient.embed_text(" ".join(extracted_feedback), {"source": "feedback"})
-> BaseMcpClient.call_tool("embed_text")
```

```text
MemoryAgent
-> Neo4jClient.update_profile(snapshot, extracted, sentiment)
-> BaseMcpClient.call_tool("update_user_interest_graph")
```

注意当前代码没有把反馈向量写入 Milvus:

- `memory_update_skill.md` 设计里提到 `insert_memory_vector`。
- 但 `MemoryAgent.run` 目前只调用 embedding 和 Neo4j update。
- 所以“长期向量记忆写入 Milvus”在当前 MVP 中还没有实现。

### 3.6 反馈链路中哪里写 MySQL

| 表 | 文件/函数 | 写入内容 |
|---|---|---|
| `run_logs` | `harness.go` `writeFeedbackRunLog` -> `mysql.go` `InsertRunLog` | 反馈运行状态、steps、sentiment |
| `feedback_logs` | `mysql.go` `InsertFeedbackLog` | 用户原始反馈 |
| `user_profile_snapshot` | `mysql.go` `InsertUserProfileSnapshot` | 更新后的画像快照 |
| `mcp_call_logs` | `mysql.go` `InsertMcpCallLogs` | MemoryAgent 的 embedding 和 Neo4j MCP 调用日志 |

### 3.7 反馈链路中的 mock 点

| mock 点 | 位置 | 当前行为 |
|---|---|---|
| LLM mock | `llm_tool.py` `MockLLMClient` | 默认用 rating 和关键词判断 sentiment，抽取 feedback_text |
| Embedding mock | `MockMcpTransport` 或 `mcp-servers/embedding-mcp/server.py` | 生成 deterministic/mock embedding |
| Neo4j mock | `MockMcpTransport` 或 `mcp-servers/neo4j-mcp/server.py` | 更新内存用户兴趣图，非真实 Neo4j |
| MCP transport mock | `ArticleWorkflow.__init__` | `settings.mock_mcp=true` 时使用进程内 mock |
| Milvus 记忆 | 当前未写入 | 虽然有 MilvusClient 和 skill 设计，但反馈链路没有调用 `insert_memory_vector` |

## 四、LLM 调用汇总

| 链路 | Agent | 文件/函数 | LLMTool 方法 | 输出 schema |
|---|---|---|---|---|
| 文章 | SummaryAgent | `summary_agent.py` `run` | `LLMTool.summarize` | `SummaryLLMOutput(summary, issues)` |
| 文章 | RewriteAgent | `rewrite_agent.py` `run` | `LLMTool.rewrite_post` | `RewriteLLMOutput(post_text, issues)` |
| 反馈 | FeedbackAgent | `feedback_agent.py` `run` | `LLMTool.extract_feedback` | `FeedbackLLMOutput(sentiment, extracted_feedback, issues)` |

LLM provider 入口在 `python-agent/app/tools/llm_tool.py`:

```text
build_llm_tool
-> build_llm_client
-> MockLLMClient / OpenAICompatibleLLMClient / ClaudeLLMClient stub
```

稳定性机制:

```text
provider.complete_json
-> _parse_json
-> Pydantic model_validate
-> 失败则 repair 一次
-> repair 失败则 mock fallback，并追加 llm_fallback issue
```

## 五、MCP 调用汇总

| 链路 | Agent | 文件/函数 | MCP Client | Tool | 默认是否会走 |
|---|---|---|---|---|---|
| 文章 | FilterAgent | `filter_agent.py` `run` | `Neo4jClient` | `query_user_interest_graph` | 会，`EnableNeo4J=true` |
| 文章 | FilterAgent | `filter_agent.py` `run` | `EmbeddingClient` | `embed_text` | 会，`EnableEmbedding=true` |
| 文章 | FilterAgent | `filter_agent.py` `run` | `MilvusClient` | `search_similar_memory` | 会，前提是 embedding 成功且 `EnableMilvus=true` |
| 文章 | FilterAgent | `filter_agent.py` `run` | `FetchClient` | `fetch_webpage` | 默认不会，`EnableFetch=false`；手动开启也会被 filter 权限拒绝 |
| 反馈 | MemoryAgent | `memory_agent.py` `run` | `EmbeddingClient` | `embed_text` | 会，`EnableEmbedding=true` |
| 反馈 | MemoryAgent | `memory_agent.py` `run` | `Neo4jClient` | `update_user_interest_graph` | 会，`EnableNeo4J=true` |

所有 MCP 调用都经过:

```text
BaseMcpClient.call_tool
-> MCPPolicy.check(agent_name, tool_name)
-> MockMcpTransport 或 JsonRpcMcpTransport
-> 生成 McpCallResult(result, log)
```

权限失败:

```text
status = denied
success = false
error.code = MCP_PERMISSION_DENIED
不调用 transport
```

调用失败:

```text
status = failed
success = false
error.code = MCP_CALL_FAILED
workflow 降级继续
```

## 六、MySQL 写入汇总

| 链路 | 表 | 文件/函数 | 时机 |
|---|---|---|---|
| 文章 | `run_logs` | `harness.go` `writeRunLog` / `mysql.go` `InsertRunLog` | run 开始、文章保存后、完成或失败 |
| 文章 | `articles` | `mysql.go` `InsertArticle` | RSS 去重后逐篇写入 |
| 文章 | `posts` | `mysql.go` `InsertPost` | Python 返回后，`keep=true` 且 `post_text` 非空 |
| 文章 | `mcp_call_logs` | `mysql.go` `InsertMcpCallLogs` | Python response 带回 MCP logs 后 |
| 反馈 | `run_logs` | `harness.go` `writeFeedbackRunLog` / `mysql.go` `InsertRunLog` | feedback run 开始、完成或失败 |
| 反馈 | `feedback_logs` | `mysql.go` `InsertFeedbackLog` | 调 Python 前先保存原始反馈 |
| 反馈 | `user_profile_snapshot` | `mysql.go` `InsertUserProfileSnapshot` | Python 返回 updated profile 后 |
| 反馈 | `mcp_call_logs` | `mysql.go` `InsertMcpCallLogs` | Python response 带回 MemoryAgent MCP logs 后 |

## 七、当前代码与目标设计的差异点

这些点对理解调用链很重要，避免把 mock 或未实现能力误认为真实能力:

1. `McpPolicy.mock_transport` 在 proto 里存在，但当前实际 transport 选择由 Python 启动配置 `MOCK_MCP` / `settings.mock_mcp` 决定。
2. `CheckAgent` 当前只检查 `summary`、`post_text`、`url` 是否存在，不调用 MCP，也不做真实事实核查、URL alive、语义去重。
3. `SummaryAgent` skill 文档允许 fetch/search，但当前 `SummaryAgent.run` 只调用 LLM，不调用 MCP。
4. `FeedbackAgent` skill 文档允许 embedding/search_similar_memory，但当前 `FeedbackAgent.run` 只调用 LLM，不调用 MCP。
5. `MemoryAgent` 当前调用 embedding 和 Neo4j update，但没有调用 Milvus `insert_memory_vector`，所以反馈向量长期存储还没实现。
6. 默认 RSS source 是 `mock://sample`，所以不联网也能跑文章链路。
7. 默认 LLM provider 是 `mock`，OpenAI 缺 API key 时也会 fallback 到 mock。
8. Milvus 和 Neo4j 当前是 mock/内存模拟，不是真实生产数据库链路。

## 八、一句话总结

文章链路是: GoFrame 抓文章并落库，gRPC 交给 Python Agent 做 `Filter -> Summary -> Rewrite -> Check`，再把结果保存为 `posts` 和 Markdown。  
反馈链路是: GoFrame 先保存原始反馈，gRPC 交给 Python 做 `Feedback -> Memory`，再把 `updated_profile_snapshot` 写回 MySQL，供下一次文章筛选使用。
