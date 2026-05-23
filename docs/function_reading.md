# KnowMate 函数级精读

> 本文按 README 推荐的主流程展开: `POST /runs/articles` 进入 GoFrame，经过 RSS/MySQL/gRPC 到 Python Agent，Python 内部执行 `Filter -> Summary -> Rewrite -> Check`；反馈流程是 `POST /feedback -> Feedback -> Memory`。  
> 本文不修改代码，只解释当前实现。当前 MVP 中，LLM 默认 mock，MCP/Milvus/Neo4j 默认 mock 或内存模拟。

## 主流程入口图

```text
文章处理:
GoFrame /runs/articles
-> Harness.RunArticles
-> RSSCrawler.Fetch
-> Store.InsertArticle
-> gRPC ProcessArticles
-> AgentService.ProcessArticles
-> ArticleWorkflow.process_articles
-> FilterAgent
-> SummaryAgent
-> RewriteAgent
-> CheckAgent
-> ProcessArticlesResponse
-> Store.InsertPost
-> Markdown

反馈处理:
GoFrame /feedback
-> Store.InsertFeedbackLog
-> gRPC ProcessFeedback
-> AgentService.ProcessFeedback
-> ArticleWorkflow.process_feedback
-> FeedbackAgent
-> MemoryAgent
-> updated_profile_snapshot
-> Store.InsertUserProfileSnapshot
```

---

# python-agent/app/workflow/graph.py

## 这个文件的整体作用

`graph.py` 是 Python Agent 的工作流总控文件。它负责把 skill、LLMTool、MCP client 和 6 个 Agent 组装起来，并提供两个对外入口:

- `process_articles`: 文章处理流程。
- `process_feedback`: 用户反馈流程。

如果安装了 LangGraph，它会构建 `StateGraph`；如果没有安装 LangGraph，它会 fallback 到普通 Python 顺序执行。

## 它被谁调用

- `python-agent/app/grpc_server.py` 中的 `AgentService.__init__` 会创建 `ArticleWorkflow(settings)`。
- `AgentService.ProcessArticles` 调用 `ArticleWorkflow.process_articles`。
- `AgentService.ProcessFeedback` 调用 `ArticleWorkflow.process_feedback`。

## 它调用了谁

- `app.skill_loader.load_skills`
- `app.tools.build_llm_tool`
- `app.mcp.EmbeddingClient`、`FetchClient`、`MilvusClient`、`Neo4jClient`
- `app.mcp.MockMcpTransport` 或 `JsonRpcMcpTransport`
- `app.mcp.MCPPolicy`
- 6 个 Agent: `FilterAgent`、`SummaryAgent`、`RewriteAgent`、`CheckAgent`、`FeedbackAgent`、`MemoryAgent`
- 可选调用 `langgraph.graph.StateGraph` 和 `END`

## 重要类和函数列表

- `ArticleWorkflow.__init__`
- `ArticleWorkflow.process_articles`
- `ArticleWorkflow.process_feedback`
- `ArticleWorkflow.enabled_agents`
- `ArticleWorkflow._run_article_sequential`
- `ArticleWorkflow._run_feedback_sequential`
- `ArticleWorkflow._try_build_article_langgraph`
- `ArticleWorkflow._try_build_feedback_langgraph`

## 函数逐个讲解

### ArticleWorkflow.__init__

【作用】  
初始化整条 Agent 工作流: 读取 skill，选择 MCP transport，创建 MCP client，创建 LLMTool，创建所有 Agent，并尝试编译 LangGraph。

【参数】  
- `settings: Settings`: Python Agent 的运行配置，包含 LLM provider、MCP URL、是否 mock MCP 等。

【返回值】  
无显式返回值。Python 构造函数默认返回 `None`，但会把成员变量挂到 `self` 上。

【执行流程】

1. 读取所有 skill markdown。
2. 根据 `settings.mock_mcp` 选择进程内 mock transport 或 HTTP JSON-RPC transport。
3. 创建统一 MCP 权限策略。
4. 创建 embedding/fetch/milvus/neo4j client。
5. 创建 LLMTool。
6. 创建 6 个 Agent。
7. 尝试创建文章 LangGraph。
8. 尝试创建反馈 LangGraph。

【逐行解释】

- `skills = load_skills()`: 调用 skill loader，把 `app/skills/*.md` 读成字典。key 是文件名去掉 `.md`，value 是文件文本。
- `transport = MockMcpTransport() if settings.mock_mcp else JsonRpcMcpTransport(settings.mcp_urls)`: Python 三元表达式。`settings.mock_mcp` 为真时使用进程内 mock；否则使用 HTTP JSON-RPC transport。
- `mcp_policy = MCPPolicy()`: 创建默认 MCP 权限矩阵。所有 MCP 调用都会经过它。
- `embedding_client = EmbeddingClient(transport, policy=mcp_policy)`: 创建 embedding 工具客户端，底层共享同一个 transport 和 policy。
- `fetch_client = FetchClient(...)`: 创建网页抓取工具客户端。当前默认文章链路中 `enable_fetch=false`，通常不走。
- `milvus_client = MilvusClient(...)`: 创建向量记忆客户端。当前默认是 mock。
- `neo4j_client = Neo4jClient(...)`: 创建用户兴趣图客户端。当前默认是 mock。
- `llm_tool = build_llm_tool(settings)`: 根据配置创建 LLMTool，可能是 mock、openai-compatible 或 claude stub。
- `self.llm_tool = llm_tool`: 保存到实例上，HealthCheck 会用它判断 provider。
- `self.filter_agent = FilterAgent(...)`: 创建 FilterAgent，并注入 skill 和 MCP clients。
- `skills.get("filter_skill", "")`: 从 skill 字典取 `filter_skill.md`，取不到则给空字符串。
- `self.summary_agent = SummaryAgent(...)`: 创建 SummaryAgent，注入 `summary_skill.md` 和 LLMTool。
- `self.rewrite_agent = RewriteAgent(...)`: 创建 RewriteAgent，注入 `rewrite_post_skill.md` 和 LLMTool。
- `self.check_agent = CheckAgent(...)`: 创建 CheckAgent，注入 `fact_check_skill.md`。注意当前 CheckAgent 代码没有使用 skill 文本做复杂检查。
- `self.feedback_agent = FeedbackAgent(...)`: 创建 FeedbackAgent，注入反馈抽取 skill 和 LLMTool。
- `self.memory_agent = MemoryAgent(...)`: 创建 MemoryAgent，注入 memory skill、embedding client、neo4j client。
- `self._article_graph = self._try_build_article_langgraph()`: 尝试构建文章 LangGraph。失败则为 `None`。
- `self._feedback_graph = self._try_build_feedback_langgraph()`: 尝试构建反馈 LangGraph。失败则为 `None`。

【涉及语法】

- 类构造函数 `__init__`。
- 实例属性 `self.xxx`。
- 三元表达式 `a if condition else b`。
- 依赖注入: 把 client/tool 传给 Agent，而不是 Agent 自己创建。
- 字典 `.get(key, default)`。

【和项目整体流程的关系】

这是 Python Agent 的装配中心。GoFrame 通过 gRPC 只知道 `ProcessArticles` 和 `ProcessFeedback`，真正决定调用哪些 Agent、走 mock MCP 还是 HTTP MCP、用哪个 LLM provider，都在这里完成。

### ArticleWorkflow.process_articles

【作用】  
处理文章 gRPC 请求，把输入 request 转成 workflow state，执行文章 Agent 流程，然后整理成可返回给 gRPC server 的 dict。

【参数】  
- `request: JsonDict`: 从 protobuf request 转来的 Python 字典，包含 `run_id`、`articles`、`user_profile_snapshot`、`mcp_policy`。

【返回值】  
返回 dict:

```python
{
    "run_id": "...",
    "results": [...]
}
```

【执行流程】

1. 构造 state。
2. 标准化 run_id。
3. 标准化文章字段。
4. 合并 MCP 默认策略。
5. 如果 LangGraph 可用则 `invoke`，否则顺序执行。
6. 把 `article_results` 转成 gRPC 友好的 `results`。

【逐行解释】

- `state: JsonDict = { ... }`: 创建工作流共享状态。`JsonDict` 是类型别名，表示 `dict[str, Any]`。
- `"run_id": ensure_run_id(request.get("run_id"))`: 如果请求有 run_id 就用它；没有则自动生成一个。
- `"articles": [normalize_article(article) for article in request.get("articles", [])]`: 列表推导式。把每篇文章都整理成统一字段。
- `request.get("articles", [])`: 没有 articles 时默认空列表，避免循环报错。
- `"user_profile_snapshot": dict(request.get("user_profile_snapshot", {}))`: 复制用户画像。`dict(...)` 避免修改原对象。
- `"mcp_policy": default_mcp_policy(request.get("mcp_policy", {}))`: 合并默认 MCP 开关。默认启用 embedding、milvus、neo4j，默认不启用 fetch。
- `result = self._article_graph.invoke(state) if self._article_graph else self._run_article_sequential(state)`: 有 LangGraph 就执行图；没有就顺序执行。这里也是三元表达式。
- `return { ... }`: 返回最终结构。
- `"run_id": result["run_id"]`: 保留 workflow 的 run_id。
- `"results": [ ... for item in result.get("article_results", []) ]`: 把内部状态中的 `article_results` 列表转换成外部 response 列表。
- `"article_id": item.get("article_id", "")`: 取文章 ID，缺失时给空字符串。
- `"keep": bool(item.get("keep", False))`: 转成布尔值，避免返回奇怪类型。
- `"score": float(item.get("score", 0))`: 转成浮点数。
- `"summary": str(item.get("summary", ""))`: 转成字符串。
- `"post_text": str(item.get("post_text", ""))`: 转成字符串。
- `"check_pass": bool(item.get("check_pass", False))`: 转成布尔值。
- `"issues": list(item.get("issues", []))`: 转成列表。
- `"mcp_call_logs": list(item.get("mcp_call_logs", []))`: 保留 MCP 日志，后续 GoFrame 会写入 MySQL。

【涉及语法】

- 类型标注。
- 字典创建。
- 列表推导式。
- `dict.get`。
- `bool`、`float`、`str`、`list` 类型转换。
- 条件表达式。

【和项目整体流程的关系】

这是文章处理在 Python 侧的主入口。它接住 GoFrame 的 `ProcessArticlesRequest`，把文章送进 `Filter -> Summary -> Rewrite -> Check`，最终返回给 GoFrame 保存 `posts` 和 Markdown。

### ArticleWorkflow.process_feedback

【作用】  
处理反馈 gRPC 请求，把反馈列表和用户画像交给 `FeedbackAgent -> MemoryAgent`，返回更新后的画像快照。

【参数】  
- `request: JsonDict`: 从 protobuf request 转来的字典，包含 `run_id`、`feedback`、`user_profile_snapshot`、`mcp_policy`。

【返回值】  
返回 dict:

```python
{
    "run_id": "...",
    "sentiment": "...",
    "extracted_feedback": [...],
    "updated_profile_snapshot": {...},
    "mcp_call_logs": [...]
}
```

【执行流程】

1. 初始化 feedback state。
2. 创建空的 `mcp_call_logs`。
3. 执行 LangGraph 或 sequential fallback。
4. 提取 sentiment、extracted_feedback、updated_profile_snapshot、mcp_call_logs 返回。

【逐行解释】

- `state: JsonDict = { ... }`: 创建反馈工作流状态。
- `"run_id": ensure_run_id(request.get("run_id"))`: 确保有 run_id。
- `"feedback": list(request.get("feedback", []))`: 复制反馈列表，保证是 list。
- `"user_profile_snapshot": dict(...)`: 复制用户画像。
- `"mcp_policy": default_mcp_policy(...)`: 合并 MCP 默认策略。
- `"mcp_call_logs": []`: 初始化全局 MCP 日志列表。MemoryAgent 会往这里 append。
- `result = self._feedback_graph.invoke(state) if self._feedback_graph else self._run_feedback_sequential(state)`: 有图走图，没图顺序调用 FeedbackAgent 和 MemoryAgent。
- `return { ... }`: 返回 gRPC response 需要的字段。
- `"sentiment": result.get("sentiment", "neutral")`: 没有情绪时默认 neutral。
- `"extracted_feedback": result.get("extracted_feedback", [])`: 取结构化反馈。
- `"updated_profile_snapshot": result.get("updated_profile_snapshot", {})`: 取新画像。
- `"mcp_call_logs": result.get("mcp_call_logs", [])`: 取 MCP 调用日志。

【涉及语法】

- `list(...)` 和 `dict(...)` 做浅复制。
- 默认值设计。
- 条件表达式。
- 字典返回值。

【和项目整体流程的关系】

这是反馈闭环在 Python 侧的主入口。GoFrame 调用它后，会把返回的 `updated_profile_snapshot` 写入 MySQL 的 `user_profile_snapshot`，下一次文章筛选会读取这个画像。

### ArticleWorkflow.enabled_agents

【作用】  
返回当前工作流启用的 Agent 名称列表，主要给 HealthCheck 使用。

【参数】  
无。

【返回值】  
`list[str]`: `["filter", "summary", "rewrite", "check", "feedback", "memory"]`

【执行流程】  
直接返回一个固定列表。

【逐行解释】

- `def enabled_agents(self) -> list[str]:`: 定义实例方法，返回字符串列表。
- `return ["filter", ...]`: 返回当前系统支持的 Agent 名称。

【涉及语法】

- Python 列表字面量。
- 返回值类型标注 `list[str]`。

【和项目整体流程的关系】

`HealthCheck` 会把它返回给 GoFrame，方便 `/health` 展示 Python Agent 当前启用哪些 Agent。

### ArticleWorkflow._run_article_sequential

【作用】  
当 LangGraph 不可用时，用普通 Python 顺序执行文章处理 Agent。

【参数】  
- `state: JsonDict`: 工作流状态。

【返回值】  
更新后的 `state`。

【执行流程】

1. 构造 Agent 列表。
2. 按顺序执行 `filter -> summary -> rewrite -> check`。
3. 每个 Agent 都接收 state，并返回更新后的 state。

【逐行解释】

- `for agent in [self.filter_agent, ...]:`: 遍历 Agent 列表。
- `state = agent.run(state)`: 调用当前 Agent 的 `run` 方法。注意 state 会被上一个 Agent 修改后传给下一个 Agent。
- `return state`: 返回最终 state。

【涉及语法】

- `for` 循环。
- 多态: 不同 Agent 都有 `run(state)` 方法。
- 变量重新赋值。

【和项目整体流程的关系】

这是 LangGraph 的降级方案，保证即使没有安装 LangGraph，文章主流程也能跑通。

### ArticleWorkflow._run_feedback_sequential

【作用】  
当 LangGraph 不可用时，用普通 Python 顺序执行反馈 Agent。

【参数】  
- `state: JsonDict`

【返回值】  
更新后的 `state`。

【执行流程】

1. 顺序执行 `FeedbackAgent`。
2. 再执行 `MemoryAgent`。
3. 返回 state。

【逐行解释】

- `for agent in [self.feedback_agent, self.memory_agent]:`: 只遍历两个反馈相关 Agent。
- `state = agent.run(state)`: FeedbackAgent 写 `sentiment/extracted_feedback`，MemoryAgent 读取这些字段并写 `updated_profile_snapshot`。
- `return state`: 返回最终反馈状态。

【涉及语法】

- 列表。
- 循环。
- 多态方法调用。

【和项目整体流程的关系】

这是反馈流程的 sequential fallback，对应 README 里的 `Feedback Agent -> Memory Agent`。

### ArticleWorkflow._try_build_article_langgraph

【作用】  
尝试构建文章处理 LangGraph。

【参数】  
无。

【返回值】  
- 成功: 编译后的 LangGraph runnable。
- 失败: `None`。

【执行流程】

1. 尝试 import LangGraph。
2. 如果没安装，返回 `None`。
3. 创建 `StateGraph(AgentState)`。
4. 添加 4 个节点。
5. 设置入口为 `filter`。
6. 添加顺序边。
7. `check` 连到 `END`。
8. 编译图。

【逐行解释】

- `try:`: 开始异常捕获块。
- `from langgraph.graph import END, StateGraph`: 动态导入 LangGraph。放在函数内部是为了缺依赖时不影响整个模块 import。
- `except ImportError:`: 如果没有安装 LangGraph，会进入这里。
- `return None`: 返回 None，让上层走 sequential fallback。
- `graph = StateGraph(AgentState)`: 创建状态图，状态类型是 `AgentState`。
- `graph.add_node("filter", self.filter_agent.run)`: 添加 filter 节点，节点函数是 FilterAgent.run。
- `graph.add_node("summary", self.summary_agent.run)`: 添加 summary 节点。
- `graph.add_node("rewrite", self.rewrite_agent.run)`: 添加 rewrite 节点。
- `graph.add_node("check", self.check_agent.run)`: 添加 check 节点。
- `graph.set_entry_point("filter")`: 设置图的入口节点。
- `graph.add_edge("filter", "summary")`: filter 后执行 summary。
- `graph.add_edge("summary", "rewrite")`: summary 后执行 rewrite。
- `graph.add_edge("rewrite", "check")`: rewrite 后执行 check。
- `graph.add_edge("check", END)`: check 完成后结束。
- `return graph.compile()`: 编译图，得到可执行对象。

【涉及语法】

- `try/except ImportError`。
- 函数内部 import。
- 方法引用 `self.filter_agent.run`。
- 状态图节点和边。

【和项目整体流程的关系】

它把文章处理从普通函数调用升级为 LangGraph 工作流，为未来增加条件边、重试、并行和观测打基础。

### ArticleWorkflow._try_build_feedback_langgraph

【作用】  
尝试构建反馈处理 LangGraph。

【参数】  
无。

【返回值】  
- 成功: 编译后的 LangGraph runnable。
- 失败: `None`。

【执行流程】

1. 尝试导入 LangGraph。
2. 创建 `StateGraph(AgentState)`。
3. 添加 `feedback` 和 `memory` 节点。
4. 设置入口 `feedback`。
5. `feedback -> memory -> END`。
6. 编译返回。

【逐行解释】

- `try:` 和 `except ImportError:`: 和文章图一样，缺依赖时返回 None。
- `graph = StateGraph(AgentState)`: 创建反馈状态图。
- `graph.add_node("feedback", self.feedback_agent.run)`: 添加反馈抽取节点。
- `graph.add_node("memory", self.memory_agent.run)`: 添加画像更新节点。
- `graph.set_entry_point("feedback")`: 反馈流程从 feedback 节点开始。
- `graph.add_edge("feedback", "memory")`: feedback 输出给 memory。
- `graph.add_edge("memory", END)`: memory 完成后结束。
- `return graph.compile()`: 返回编译后的图。

【涉及语法】

- 异常处理。
- LangGraph API。
- 方法作为一等对象传入。

【和项目整体流程的关系】

它对应 README 中的反馈链路 `Feedback Agent -> Memory Agent`，返回的 `updated_profile_snapshot` 会被 GoFrame 写入 MySQL。

---

# python-agent/app/agents/base.py

## 这个文件的整体作用

定义所有 Agent 的基类 `BaseAgent`。它提供统一字段 `name`、统一初始化 `skill_text`，并规定子类必须实现 `run(state)`。

## 它被谁调用

- `filter_agent.py`
- `summary_agent.py`
- `rewrite_agent.py`
- `check_agent.py`
- `feedback_agent.py`
- `memory_agent.py`

这些 Agent 都继承 `BaseAgent`。

## 它调用了谁

只导入 `JsonDict`，不调用其他业务模块。

## 重要类和函数列表

- `BaseAgent.__init__`
- `BaseAgent.run`

## 函数逐个讲解

### BaseAgent.__init__

【作用】  
保存 skill 文本，让子类可以使用 prompt 或规则描述。

【参数】  
- `skill_text: str = ""`: Agent 对应 skill markdown 的文本。

【返回值】  
无。

【执行流程】  
把传入的 `skill_text` 保存到 `self.skill_text`。

【逐行解释】

- `def __init__(self, skill_text: str = "") -> None:`: 定义构造函数，参数默认空字符串。
- `self.skill_text = skill_text`: 把 skill 文本挂到实例上。

【涉及语法】

- 类继承中的构造函数。
- 默认参数。
- 实例属性。

【和项目整体流程的关系】

所有 Agent 都可以通过 `self.skill_text` 读取自己的 skill。当前 Summary/Rewrite/Feedback 会把 skill 传给 LLMTool，Filter/Check/Memory 虽然保存了 skill，但核心逻辑暂未充分使用。

### BaseAgent.run

【作用】  
定义统一接口，要求子类实现 `run(state)`。

【参数】  
- `state: JsonDict`: 工作流状态。

【返回值】  
理论上返回更新后的 `JsonDict`，但基类方法不会真正返回。

【执行流程】  
直接抛出 `NotImplementedError`。

【逐行解释】

- `def run(self, state: JsonDict) -> JsonDict:`: 规定所有 Agent 都应该有这个方法。
- `raise NotImplementedError`: 如果子类没有重写，调用时会报错，提醒开发者必须实现。

【涉及语法】

- 抽象接口风格。
- `raise` 抛异常。

【和项目整体流程的关系】

`ArticleWorkflow` 可以把不同 Agent 放进同一个列表，并统一调用 `agent.run(state)`，这就是多态。

---

# python-agent/app/agents/filter_agent.py

## 这个文件的整体作用

`FilterAgent` 负责文章筛选和打分。它根据标题、正文、URL、用户画像关键词，以及 MCP 返回的 mock Neo4j/Milvus/embedding 信号，决定文章是否进入总结和改写阶段。

## 它被谁调用

- `ArticleWorkflow._run_article_sequential`
- LangGraph 文章节点 `"filter"`

## 它调用了谁

- `EmbeddingClient.embed_text`
- `FetchClient.fetch_url`
- `MilvusClient.search_similar_memory`
- `Neo4jClient.get_profile_context`
- 自身 helper: `_score_article`、`_profile_keywords`

## 重要类和函数列表

- `FilterAgent.__init__`
- `FilterAgent.run`
- `FilterAgent._score_article`
- `FilterAgent._profile_keywords`

## 函数逐个讲解

### FilterAgent.__init__

【作用】  
初始化 FilterAgent，并保存可选的 MCP clients。

【参数】

- `skill_text`: filter skill 文本。
- `embedding_client`: embedding 工具客户端。
- `fetch_client`: fetch 工具客户端。
- `milvus_client`: 向量记忆客户端。
- `neo4j_client`: 兴趣图客户端。

【返回值】  
无。

【执行流程】

1. 调用父类构造函数保存 skill。
2. 保存四个 MCP client 到实例属性。

【逐行解释】

- `def __init__(..., embedding_client: EmbeddingClient | None = None, ...)`: 使用联合类型，表示参数可以是对应 client，也可以是 None。
- `super().__init__(skill_text)`: 调用 `BaseAgent.__init__` 保存 skill 文本。
- `self.embedding_client = embedding_client`: 保存 embedding client。
- `self.fetch_client = fetch_client`: 保存 fetch client。
- `self.milvus_client = milvus_client`: 保存 milvus client。
- `self.neo4j_client = neo4j_client`: 保存 neo4j client。

【涉及语法】

- `super()` 调父类方法。
- `类型 | None` 是 Python 3.10 的联合类型写法。
- 依赖注入。

【和项目整体流程的关系】

FilterAgent 是文章链路第一个 Agent，它的输出 `keep` 决定后续 Summary/Rewrite 是否处理该文章。

### FilterAgent.run

【作用】  
遍历输入文章，计算每篇文章的筛选分数，生成 `article_results`。

【参数】  
- `state: JsonDict`: 包含 `run_id`、`articles`、`user_profile_snapshot`、`mcp_policy`。

【返回值】  
更新后的 `state`，新增 `article_results`。

【执行流程】

1. 读取 run_id、用户画像、MCP 策略。
2. 遍历文章。
3. 可选 fetch 缺失正文。
4. 本地规则打分。
5. 可选 Neo4j 兴趣图加权。
6. 可选 embedding。
7. 可选 Milvus 相似记忆加权。
8. 根据 `score >= 0.5` 和标题存在决定 keep。
9. 写入 `state["article_results"]`。

【逐行解释】

- `run_id = str(state.get("run_id", ""))`: 从 state 取 run_id，转成字符串，供 MCP 日志使用。
- `profile = state.get("user_profile_snapshot", {})`: 获取用户画像字典。
- `policy = state.get("mcp_policy", {})`: 获取 MCP 开关。
- `article_results = []`: 准备收集每篇文章的结果。
- `for article in state.get("articles", []):`: 遍历文章列表，缺失时默认空列表。
- `logs: list[JsonDict] = []`: 当前文章的 MCP 调用日志。
- `if policy.get("enable_fetch") ...`: 如果开启 fetch、文章没有正文、有 URL、有 fetch client，则尝试抓网页。
- `fetched = self.fetch_client.fetch_url(...)`: 调用 FetchClient。注意当前 filter 权限不允许 `fetch_webpage`，如果走到这里通常会被 MCPPolicy 拒绝。
- `logs.append(fetched.log)`: 保存 fetch 的 MCP 日志。
- `article["raw_text"] = str(fetched.result.get("raw_text", ""))`: 把 fetch 结果写回文章正文。
- `score, reasons = self._score_article(article, profile)`: 调本地打分函数，返回分数和原因。
- `if policy.get("enable_neo4j") and self.neo4j_client:`: 如果启用 Neo4j 且 client 存在。
- `context = self.neo4j_client.get_profile_context(...)`: 查询用户兴趣图上下文。
- `logs.append(context.log)`: 保存 Neo4j 调用日志。
- `if context.result.get("topics"):`: 如果 mock/真实结果中有 topics。
- `score = min(score + 0.05, 1.0)`: 加权 0.05，最高不超过 1.0。
- `reasons.append("mock-profile-context")`: 记录这个加分来自画像上下文，目前是 mock 信号。
- `embedding: list[float] = []`: 初始化向量为空列表。
- `if policy.get("enable_embedding") and self.embedding_client:`: 如果启用 embedding。
- `embedded = self.embedding_client.embed_text(...)`: 把标题和正文拼接后送去 embedding。
- `f"{article.get('title', '')}\n{article.get('raw_text', '')}"`: f-string，生成“标题 + 换行 + 正文”。
- `logs.append(embedded.log)`: 保存 embedding 调用日志。
- `embedding = list(embedded.result.get("embedding", []))`: 从结果里取 embedding。失败时没有 embedding，会得到空列表。
- `if policy.get("enable_milvus") and embedding and self.milvus_client:`: 启用 Milvus、embedding 非空、client 存在才搜索相似记忆。
- `related = self.milvus_client.search_similar_memory(...)`: 调 Milvus client 搜索相似记忆。
- `logs.append(related.log)`: 保存 Milvus 日志。
- `if related.result.get("matches"):`: 如果有相似结果。
- `score = min(score + 0.05, 1.0)`: 再加一点分。
- `reasons.append("mock-related-articles")`: 记录 mock 相似文章信号。
- `keep = score >= 0.5 and bool(article.get("title"))`: 分数至少 0.5 且有标题才保留。
- `article_results.append({...})`: 追加本篇文章处理结果。
- `"article": article`: 保存原文章，后续 Summary/Rewrite 会用。
- `"article_id": article["article_id"]`: 保存文章 ID。
- `"keep": keep`: 保存筛选结果。
- `"score": round(score, 4)`: 分数保留 4 位小数。
- `"summary": ""`: 给 SummaryAgent 预留字段。
- `"post_text": ""`: 给 RewriteAgent 预留字段。
- `"check_pass": False`: 初始未通过，后续 CheckAgent 更新。
- `"issues": [] if keep else ["filtered_out"]`: 三元表达式。被过滤则记录问题。
- `"mcp_call_logs": logs`: 保存 MCP 日志。
- `"filter_reasons": reasons`: 保存筛选原因，当前不会进入 gRPC response。
- `state["article_results"] = article_results`: 写回 workflow state。
- `return state`: 返回给下一个 Agent。

【涉及语法】

- 字典读取 `.get`。
- 列表追加 `.append`。
- 类型标注 `list[float]`。
- f-string。
- 条件表达式。
- `min`、`round`。
- 布尔短路 `and`。

【和项目整体流程的关系】

FilterAgent 是文章处理的入口节点。它决定哪些文章值得花 LLM 成本总结和改写，也负责产生文章链路中主要的 MCP 调用日志。

### FilterAgent._score_article

【作用】  
用本地规则给文章打基础分，不依赖 LLM 或 MCP。

【参数】

- `article: JsonDict`: 单篇文章。
- `profile: JsonDict`: 用户画像。

【返回值】  
`tuple[float, list[str]]`: 分数和打分原因列表。

【执行流程】

1. 提取标题和正文。
2. 构造小写搜索文本。
3. 初始分 0.1。
4. 标题、URL、正文长度分别加分。
5. 从画像中提取关键词。
6. 如果关键词命中文章文本，按命中数加分。
7. 分数最高限制 1.0。

【逐行解释】

- `title = str(article.get("title", "")).strip()`: 取标题，转字符串，去掉首尾空白。
- `raw_text = str(article.get("raw_text", "")).strip()`: 取正文并清理空白。
- `haystack = f"{title} {raw_text}".lower()`: 拼成搜索文本并转小写，方便关键词匹配。
- `score = 0.1`: 设置基础分。
- `reasons: list[str] = []`: 初始化原因列表。
- `if title:`: 如果标题非空。
- `score += 0.25`: 有标题加分。
- `reasons.append("has-title")`: 记录原因。
- `if article.get("url"):`: 有 URL 加分。
- `score += 0.1`: URL 加 0.1。
- `reasons.append("has-url")`: 记录原因。
- `if len(raw_text) >= 80:`: 正文长度至少 80 字符。
- `score += 0.25`: 正文足够长加较多分。
- `reasons.append("has-enough-text")`: 记录原因。
- `elif raw_text:`: 如果正文不够长但不为空。
- `score += 0.12`: 短正文加少量分。
- `reasons.append("has-short-text")`: 记录原因。
- `keywords = self._profile_keywords(profile)`: 从用户画像提取关键词。
- `matched = [word for word in keywords if word and word.lower() in haystack]`: 列表推导式，找到命中的关键词。
- `if matched:`: 如果有命中。
- `score += min(0.25, 0.08 * len(matched))`: 每个命中加 0.08，最多加 0.25。
- `reasons.append("matches-user-profile:" + ",".join(matched[:3]))`: 记录最多前三个命中词。
- `return min(score, 1.0), reasons`: 返回最高不超过 1.0 的分数和原因。

【涉及语法】

- 字符串 `.strip()`、`.lower()`。
- `len()`。
- `if/elif`。
- 列表推导式。
- 切片 `matched[:3]`。
- 字符串拼接和 `",".join(...)`。

【和项目整体流程的关系】

这是 FilterAgent 的基础判断逻辑。即使 MCP 全部失败，系统仍能基于本地规则给文章打分并继续处理。

### FilterAgent._profile_keywords

【作用】  
从用户画像中提取兴趣关键词，用于文章本地打分。

【参数】  
- `profile: JsonDict`: 用户画像。

【返回值】  
`list[str]`: 关键词列表。

【执行流程】

1. 遍历画像中几个可能含关键词的字段。
2. 如果字段是字符串，就按逗号或分号切分。
3. 如果字段是列表，就逐项转字符串。
4. 去掉空字符串后返回。

【逐行解释】

- `values = []`: 初始化关键词列表。
- `for key in ["interests", "topics", "keywords", "preferred_tags"]:`: 遍历可能的画像字段名。
- `raw = profile.get(key, "")`: 取字段值，默认空字符串。
- `if isinstance(raw, str):`: 如果是字符串。
- `raw.replace(";", ",").split(",")`: 先把分号换成逗号，再按逗号切分。
- `values.extend(part.strip() for part in ...)`: 生成器表达式逐个去空白，并追加到 values。
- `elif isinstance(raw, list):`: 如果画像字段已经是列表。
- `values.extend(str(part).strip() for part in raw)`: 每项转字符串并去空白。
- `return [value for value in values if value]`: 返回非空关键词。

【涉及语法】

- `isinstance` 类型判断。
- 列表 `.extend`。
- 生成器表达式。
- 列表推导式。

【和项目整体流程的关系】

反馈流程更新 `user_profile_snapshot` 后，下一次文章流程会通过这个函数读取画像关键词，从而影响 FilterAgent 打分。

---

# python-agent/app/agents/summary_agent.py

## 这个文件的整体作用

`SummaryAgent` 对保留下来的文章调用 LLMTool，生成中文摘要。

## 它被谁调用

- LangGraph 节点 `"summary"`。
- `_run_article_sequential` 中 FilterAgent 之后。

## 它调用了谁

- `LLMTool.summarize`
- 可能调用 `build_llm_tool(Settings())` 作为默认工具。

## 重要类和函数列表

- `SummaryAgent.__init__`
- `SummaryAgent.run`

## 函数逐个讲解

### SummaryAgent.__init__

【作用】  
初始化 SummaryAgent，保存 skill，并确保有 LLMTool。

【参数】

- `skill_text`: summary skill 文本。
- `llm_tool`: 可选 LLMTool。

【返回值】  
无。

【执行流程】

1. 调父类保存 skill。
2. 如果外部传入 LLMTool 就用外部的。
3. 如果没传，就用默认 `Settings()` 创建一个。

【逐行解释】

- `def __init__(self, skill_text: str = "", llm_tool: LLMTool | None = None) -> None:`: 定义构造函数，LLMTool 可为空。
- `super().__init__(skill_text)`: 保存 skill 文本。
- `self.llm_tool = llm_tool or build_llm_tool(Settings())`: Python 的 `or` 会返回第一个真值。传了 llm_tool 就用它，否则构建默认 mock 工具。

【涉及语法】

- `or` 短路求值。
- 依赖注入。
- 默认配置对象。

【和项目整体流程的关系】

在实际 workflow 中，`ArticleWorkflow` 会传入统一的 `llm_tool`，保证 Summary/Rewrite/Feedback 使用同一个 provider。

### SummaryAgent.run

【作用】  
遍历文章结果，对 `keep=true` 的文章生成摘要。

【参数】  
- `state: JsonDict`

【返回值】  
更新后的 `state`。

【执行流程】

1. 复制用户画像。
2. 遍历 `article_results`。
3. 跳过被过滤的文章。
4. 调用 LLMTool 生成摘要。
5. 写入 `summary`。
6. 追加 LLM issues。

【逐行解释】

- `profile = dict(state.get("user_profile_snapshot", {}))`: 复制用户画像。
- `for result in state.get("article_results", []):`: 遍历 FilterAgent 生成的结果。
- `if not result.get("keep"):`: 如果文章不保留。
- `continue`: 跳过当前 result。
- `output = self.llm_tool.summarize(result["article"], profile, self.skill_text)`: 调 LLMTool。输入是原文章、用户画像和 summary skill。
- `result["summary"] = output.summary`: 把结构化输出中的 summary 写回 result。
- `if output.issues:`: 如果 LLMTool 返回问题，比如 fallback。
- `result.setdefault("issues", []).extend(output.issues)`: 确保 result 有 issues 列表，然后追加问题。
- `return state`: 返回更新后的 state。

【涉及语法】

- `continue`。
- `dict(...)` 浅复制。
- 对象属性访问 `output.summary`。
- `setdefault`。
- `extend`。

【和项目整体流程的关系】

SummaryAgent 是文章链路第一个 LLM 调用点。它的输出 `summary` 是 RewriteAgent 的输入。

---

# python-agent/app/agents/rewrite_agent.py

## 这个文件的整体作用

`RewriteAgent` 把摘要改写成适合发布的 Markdown 知识帖。

## 它被谁调用

- LangGraph 节点 `"rewrite"`。
- `_run_article_sequential` 中 SummaryAgent 之后。

## 它调用了谁

- `LLMTool.rewrite_post`
- 可能调用 `build_llm_tool(Settings())` 作为默认工具。

## 重要类和函数列表

- `RewriteAgent.__init__`
- `RewriteAgent.run`

## 函数逐个讲解

### RewriteAgent.__init__

【作用】  
初始化 RewriteAgent，保存 skill 和 LLMTool。

【参数】

- `skill_text`: rewrite skill 文本。
- `llm_tool`: 可选 LLMTool。

【返回值】  
无。

【执行流程】  
和 SummaryAgent 类似，保存 skill，并设置 LLMTool。

【逐行解释】

- `def __init__(..., llm_tool: LLMTool | None = None)`: LLMTool 可以外部注入。
- `super().__init__(skill_text)`: 保存 skill。
- `self.llm_tool = llm_tool or build_llm_tool(Settings())`: 使用传入工具或创建默认工具。

【涉及语法】

- 父类构造。
- `or` 默认值。

【和项目整体流程的关系】

`ArticleWorkflow` 传入统一 LLMTool，让 RewriteAgent 和 SummaryAgent 使用同一个 provider。

### RewriteAgent.run

【作用】  
对保留文章调用 LLMTool，把 summary 改写为 `post_text`。

【参数】  
- `state: JsonDict`

【返回值】  
更新后的 `state`。

【执行流程】

1. 遍历 `article_results`。
2. 跳过 `keep=false`。
3. 调用 `rewrite_post`。
4. 写入 `post_text`。
5. 追加 issues。

【逐行解释】

- `for result in state.get("article_results", []):`: 遍历文章结果。
- `if not result.get("keep"):`: 不保留的文章不改写。
- `continue`: 进入下一篇。
- `output = self.llm_tool.rewrite_post(result["article"], str(result.get("summary", "")), self.skill_text)`: 调 LLMTool。`str(...)` 确保 summary 是字符串。
- `result["post_text"] = output.post_text`: 写入 Markdown 正文。
- `if output.issues:`: 如果有问题。
- `result.setdefault("issues", []).extend(output.issues)`: 追加问题。
- `return state`: 返回 state。

【涉及语法】

- `str(...)` 类型转换。
- 列表遍历。
- `setdefault`。

【和项目整体流程的关系】

RewriteAgent 的 `post_text` 最终会被 GoFrame 写入 MySQL `posts.markdown`，并输出到 Markdown 文件。

---

# python-agent/app/agents/check_agent.py

## 这个文件的整体作用

`CheckAgent` 负责对生成结果做最后检查。当前 MVP 只做字段级本地检查，不调用 LLM，不调用 MCP。

## 它被谁调用

- LangGraph 节点 `"check"`。
- `_run_article_sequential` 中 RewriteAgent 之后。

## 它调用了谁

当前不调用外部工具，只操作 state。

## 重要类和函数列表

- `CheckAgent.run`

## 函数逐个讲解

### CheckAgent.run

【作用】  
检查每个文章结果是否满足最低发布要求。

【参数】  
- `state: JsonDict`

【返回值】  
更新后的 `state`。

【执行流程】

1. 遍历文章结果。
2. 复制已有 issues。
3. 如果文章被过滤，标记 `check_pass=false`。
4. 检查 summary、post_text、url。
5. 无问题则 `check_pass=true`。

【逐行解释】

- `for result in state.get("article_results", []):`: 遍历所有文章结果。
- `issues = list(result.get("issues", []))`: 复制已有问题列表。
- `article = result.get("article", {})`: 取原文章。
- `if not result.get("keep"):`: 如果不保留。
- `result["check_pass"] = False`: 被过滤文章不通过检查。
- `result["issues"] = issues`: 保留已有问题。
- `continue`: 跳过后续检查。
- `if not result.get("summary"):`: 如果摘要为空。
- `issues.append("missing_summary")`: 添加问题。
- `if not result.get("post_text"):`: 如果推文正文为空。
- `issues.append("missing_post_text")`: 添加问题。
- `if not article.get("url"):`: 如果原文 URL 为空。
- `issues.append("missing_url")`: 添加问题。
- `result["issues"] = issues`: 写回问题列表。
- `result["check_pass"] = len(issues) == 0`: 如果没有任何问题，则通过。
- `return state`: 返回 state。

【涉及语法】

- `list(...)` 浅复制。
- `len(...) == 0`。
- 多个独立 `if`，不是 `elif`，所以会同时记录多个问题。

【和项目整体流程的关系】

`check_pass` 会影响 GoFrame 保存 post 的 status: 通过则 `ready`，不通过则 `check_failed`。

---

# python-agent/app/agents/feedback_agent.py

## 这个文件的整体作用

`FeedbackAgent` 从用户反馈中抽取结构化偏好信号，并判断反馈情绪。

## 它被谁调用

- LangGraph 节点 `"feedback"`。
- `_run_feedback_sequential` 中第一个 Agent。

## 它调用了谁

- `LLMTool.extract_feedback`
- 可能调用 `build_llm_tool(Settings())` 创建默认 LLMTool。

## 重要类和函数列表

- `FeedbackAgent.__init__`
- `FeedbackAgent.run`

## 函数逐个讲解

### FeedbackAgent.__init__

【作用】  
保存 feedback skill，并设置 LLMTool。

【参数】

- `skill_text`: feedback skill 文本。
- `llm_tool`: 可选 LLMTool。

【返回值】  
无。

【执行流程】  
和 SummaryAgent/RewriteAgent 一样，保存 skill，设置 LLMTool。

【逐行解释】

- `super().__init__(skill_text)`: 保存 skill。
- `self.llm_tool = llm_tool or build_llm_tool(Settings())`: 优先使用 workflow 注入的 LLMTool，否则创建默认工具。

【涉及语法】

- `super()`。
- `or` 短路。

【和项目整体流程的关系】

FeedbackAgent 是反馈闭环中第一个 Python Agent，它输出的结构化反馈会被 MemoryAgent 用来更新画像。

### FeedbackAgent.run

【作用】  
调用 LLMTool，把原始 feedback 转为 `sentiment` 和 `extracted_feedback`。

【参数】  
- `state: JsonDict`

【返回值】  
更新后的 `state`。

【执行流程】

1. 读取 `state["feedback"]`。
2. 调用 LLMTool。
3. 写入 `sentiment`。
4. 写入 `extracted_feedback`。
5. 如果有问题，写入 `feedback_issues`。

【逐行解释】

- `output = self.llm_tool.extract_feedback(list(state.get("feedback", [])), self.skill_text)`: 取反馈列表并传给 LLMTool。`list(...)` 确保输入是列表。
- `state["sentiment"] = output.sentiment`: 写入情绪。
- `state["extracted_feedback"] = output.extracted_feedback`: 写入结构化反馈。
- `if output.issues:`: 如果 LLMTool 有问题。
- `state["feedback_issues"] = output.issues`: 保存问题。
- `return state`: 返回给 MemoryAgent。

【涉及语法】

- `list(...)`。
- 对象属性访问。
- 字典赋值。

【和项目整体流程的关系】

FeedbackAgent 的输出决定 MemoryAgent 如何更新 `updated_profile_snapshot`。

---

# python-agent/app/agents/memory_agent.py

## 这个文件的整体作用

`MemoryAgent` 根据反馈抽取结果更新用户画像快照，并通过 MCP 记录 embedding 和 Neo4j 兴趣图更新。当前没有把向量写入 Milvus。

## 它被谁调用

- LangGraph 节点 `"memory"`。
- `_run_feedback_sequential` 中 FeedbackAgent 之后。

## 它调用了谁

- `EmbeddingClient.embed_text`
- `Neo4jClient.update_profile`

## 重要类和函数列表

- `MemoryAgent.__init__`
- `MemoryAgent.run`

## 函数逐个讲解

### MemoryAgent.__init__

【作用】  
初始化 MemoryAgent，保存 skill、embedding client、neo4j client。

【参数】

- `skill_text`: memory skill 文本。
- `embedding_client`: 可选 embedding MCP client。
- `neo4j_client`: 可选 Neo4j MCP client。

【返回值】  
无。

【执行流程】

1. 调用父类构造函数保存 skill。
2. 保存 embedding client。
3. 保存 neo4j client。

【逐行解释】

- `def __init__(..., embedding_client: EmbeddingClient | None = None, neo4j_client: Neo4jClient | None = None)`: 两个 client 都可以为空，便于测试或降级。
- `super().__init__(skill_text)`: 保存 skill。
- `self.embedding_client = embedding_client`: 保存 embedding client。
- `self.neo4j_client = neo4j_client`: 保存 neo4j client。

【涉及语法】

- 联合类型。
- 父类构造。
- 实例属性。

【和项目整体流程的关系】

MemoryAgent 是反馈链路中真正产出 `updated_profile_snapshot` 的节点。

### MemoryAgent.run

【作用】  
更新用户画像快照，并记录 memory 相关 MCP 调用。

【参数】  
- `state: JsonDict`

【返回值】  
更新后的 `state`。

【执行流程】

1. 读取 run_id、旧 snapshot、抽取反馈、情绪。
2. 获取或创建 `mcp_call_logs`。
3. 如果启用 embedding，调用 `embed_text`。
4. 更新 snapshot 字段。
5. 如果启用 Neo4j，调用 `update_profile`。
6. 写入 `updated_profile_snapshot`。

【逐行解释】

- `run_id = str(state.get("run_id", ""))`: 读取 run_id，转字符串。
- `snapshot = dict(state.get("user_profile_snapshot", {}))`: 复制旧画像。
- `extracted = list(state.get("extracted_feedback", []))`: 读取结构化反馈列表。
- `sentiment = str(state.get("sentiment", "neutral"))`: 读取情绪，默认 neutral。
- `logs = state.setdefault("mcp_call_logs", [])`: 如果 state 没有日志列表，就创建一个空列表；如果已有就复用。
- `if self.embedding_client and state.get("mcp_policy", {}).get("enable_embedding"):`: client 存在且策略允许 embedding 才调用。
- `embedded = self.embedding_client.embed_text(...)`: 调 embedding MCP。
- `" ".join(extracted)`: 把多条反馈拼成一个字符串。
- `{"source": "feedback"}`: 给 MCP payload 附加 metadata。
- `agent_name=self.name`: 传 Agent 名称，用于权限检查和日志。
- `run_id=run_id`: 传运行 ID，用于日志。
- `logs.append(embedded.log)`: 保存 embedding 调用日志。
- `snapshot["last_feedback_sentiment"] = sentiment`: 更新最近反馈情绪。
- `snapshot["feedback_count"] = str(int(snapshot.get("feedback_count", "0") or 0) + len(extracted))`: 读取旧反馈数，转 int，加上本次抽取数量，再转回字符串。
- `if extracted:`: 如果有抽取结果。
- `snapshot["latest_feedback"] = " | ".join(extracted[-3:])`: 保存最近最多 3 条反馈。`[-3:]` 是列表切片。
- `if self.neo4j_client and state.get("mcp_policy", {}).get("enable_neo4j"):`: 如果允许 Neo4j 更新。
- `updated = self.neo4j_client.update_profile(...)`: 调 MCP 更新用户兴趣图。
- `logs.append(updated.log)`: 保存 Neo4j 调用日志。
- `state["updated_profile_snapshot"] = snapshot`: 把新画像写回 state。
- `return state`: 返回给 workflow。

【涉及语法】

- `setdefault`。
- `" ".join(...)`。
- 切片 `extracted[-3:]`。
- `int(...)` 和 `str(...)` 类型转换。
- 布尔短路。

【和项目整体流程的关系】

GoFrame 会把 `updated_profile_snapshot` 写入 MySQL。下一次文章链路会读取它作为用户画像，从而影响 FilterAgent。

---

# python-agent/app/tools/llm_tool.py

## 这个文件的整体作用

`llm_tool.py` 是 Python Agent 的 LLM 调用统一入口。它定义结构化输出 schema、provider 抽象、mock provider、OpenAI-compatible provider、Claude stub，以及 JSON 解析、Pydantic 校验、repair、fallback 机制。

## 它被谁调用

- `SummaryAgent.run`
- `RewriteAgent.run`
- `FeedbackAgent.run`
- `ArticleWorkflow.__init__` 通过 `build_llm_tool(settings)` 创建工具。

## 它调用了谁

- 标准库 `json`、`os`、`urllib.request`
- Pydantic `BaseModel`、`Field`、`ValidationError`
- 配置对象 `Settings`、`LLMSettings`

## 重要类和函数列表

- `SummaryLLMOutput`
- `RewriteLLMOutput`
- `FeedbackLLMOutput`
- `LLMClient.complete_json`
- `MockLLMClient.complete_json`
- `OpenAICompatibleLLMClient.__init__`
- `OpenAICompatibleLLMClient.complete_json`
- `ClaudeLLMClient.__init__`
- `ClaudeLLMClient.complete_json`
- `LLMTool.__init__`
- `LLMTool.provider_name`
- `LLMTool.summarize`
- `LLMTool.rewrite_post`
- `LLMTool.extract_feedback`
- `LLMTool._generate_structured`
- `LLMTool._fallback_summary`
- `LLMTool._fallback_post`
- `LLMTool._fallback_feedback`
- `build_llm_tool`
- `build_llm_client`
- `_parse_json`
- `_validate_schema`
- `_load_prompt_payload`

## 函数逐个讲解

### SummaryLLMOutput / RewriteLLMOutput / FeedbackLLMOutput

【作用】  
这三个类不是普通函数，而是 Pydantic schema，用来规定 LLM 输出必须长什么样。

【参数】  
实例化时接收对应字段:

- `SummaryLLMOutput(summary, issues)`
- `RewriteLLMOutput(post_text, issues)`
- `FeedbackLLMOutput(sentiment, extracted_feedback, issues)`

【返回值】  
Pydantic model 实例。

【执行流程】  
Pydantic 会在 `model_validate` 时检查字段类型和约束。

【逐行解释】

- `class SummaryLLMOutput(BaseModel):`: 定义 Pydantic 模型。
- `summary: str = Field(min_length=1)`: summary 必须是字符串且长度至少 1。
- `issues: list[str] = Field(default_factory=list)`: issues 默认是新空列表，避免多个实例共享同一个列表。
- `post_text: str = Field(min_length=1)`: rewrite 输出必须有正文。
- `sentiment: Literal["positive", "neutral", "negative"] = "neutral"`: sentiment 只能是三个固定值之一。
- `extracted_feedback: list[str] = Field(default_factory=list)`: 反馈列表默认空。

【涉及语法】

- 类继承。
- Pydantic `BaseModel`。
- `Field(default_factory=list)`。
- `Literal` 限制枚举值。

【和项目整体流程的关系】

它们保证 LLM 输出结构稳定，GoFrame 才能可靠保存 `summary`、`post_text` 和反馈画像。

### LLMClient.complete_json

【作用】  
定义所有 LLM provider 必须实现的接口。

【参数】

- `task`: 任务名，如 `summary`、`rewrite`、`feedback`。
- `system_prompt`: 系统提示词。
- `user_prompt`: 用户提示词，通常是 JSON payload。

【返回值】  
字符串形式的 JSON。

【执行流程】  
基类只抛 `NotImplementedError`，具体 provider 重写。

【逐行解释】

- `class LLMClient(ABC):`: 继承抽象基类。
- `provider_name = "base"`: 默认 provider 名。
- `@abstractmethod`: 标记这个方法必须由子类实现。
- `def complete_json(...) -> str:`: 统一接口。
- `raise NotImplementedError`: 基类不提供真实实现。

【涉及语法】

- 抽象基类 `ABC`。
- 装饰器 `@abstractmethod`。
- 继承和多态。

【和项目整体流程的关系】

LLMTool 不需要关心背后是 mock、OpenAI 还是 Claude，只要调用统一的 `complete_json`。

### MockLLMClient.complete_json

【作用】  
默认 mock LLM provider，不联网，不需要 API key，用规则生成 JSON 字符串。

【参数】  
同 `LLMClient.complete_json`。

【返回值】  
JSON 字符串。

【执行流程】

1. 从 user_prompt 解析 payload。
2. 如果 task 是 summary，生成摘要 JSON。
3. 如果 task 是 rewrite，生成 Markdown post JSON。
4. 如果 task 是 feedback，基于 rating/关键词生成反馈 JSON。
5. 其他任务返回 `{}`。

【逐行解释】

- `payload = _load_prompt_payload(user_prompt)`: 把 user_prompt JSON 解析成 dict；失败返回空 dict。
- `if task == "summary":`: 分支处理摘要任务。
- `article = payload.get("article", {})`: 取文章。
- `title = str(article.get("title") or "未命名文章")`: 取标题，没有则用默认标题。
- `raw_text = str(article.get("raw_text") or "")`: 取正文。
- `compact = " ".join(raw_text.replace("\r", " ").replace("\n", " ").split())`: 把换行变空格，再按空白切分并重新拼接，压缩多余空白。
- `snippet = compact[:180] + ("..." if len(compact) > 180 else "")`: 截取前 180 字符，超长加省略号。
- `if not snippet:`: 如果正文为空。
- `snippet = "原文内容较少..."`: 使用保守占位摘要。
- `return json.dumps({...}, ensure_ascii=False)`: 返回 JSON 字符串。`ensure_ascii=False` 保留中文。
- `if task == "rewrite":`: 分支处理改写任务。
- `post_text = "\n".join([...]).strip()`: 用多行列表拼出 Markdown 文本。
- `return json.dumps({"post_text": post_text, "issues": []}, ensure_ascii=False)`: 返回改写结果。
- `if task == "feedback":`: 分支处理反馈任务。
- `positive = sum(...)`: 统计 rating >= 4 的反馈数量。
- `negative = sum(...)`: 统计 rating <= 2 的反馈数量。
- `text = " ".join(...).lower()`: 拼接反馈文本并转小写。
- `if negative > positive or any(...)`: 负面数量更多或命中负面词，则 negative。
- `elif positive > negative or any(...)`: 正面数量更多或命中正面词，则 positive。
- `else: sentiment = "neutral"`: 否则中性。
- `extracted = []`: 初始化抽取列表。
- `for item in feedback:`: 遍历反馈。
- `value = str(item.get("feedback_text", "")).strip()`: 取反馈文本。
- `if value: extracted.append(value[:200])`: 有文本则截断到 200 字符。
- `elif item.get("feedback_type"):`: 没有文本但有类型。
- `extracted.append(f"{...}")`: 用类型和 rating 生成简短信号。
- `return json.dumps({...})`: 返回反馈结构。
- `return "{}"`: 未知任务返回空 JSON。

【涉及语法】

- 条件分支。
- `json.dumps`。
- 字符串处理。
- 列表和生成器表达式。
- `sum(1 for ...)` 计数。
- `any(...)` 判断任意命中。

【和项目整体流程的关系】

这是 MVP 默认 LLM。没有真实模型时，文章和反馈链路仍能端到端跑通。

### OpenAICompatibleLLMClient.__init__

【作用】  
保存 OpenAI-compatible provider 的配置和 API key。

【参数】

- `settings: OpenAISettings`
- `api_key: str`

【返回值】  
无。

【执行流程】  
把 settings 和 api_key 保存到实例。

【逐行解释】

- `self.settings = settings`: 保存 base_url、model 等配置。
- `self.api_key = api_key`: 保存密钥。

【涉及语法】  
实例属性赋值。

【和项目整体流程的关系】  
当 `LLM_PROVIDER=openai` 且有 API key 时，LLMTool 会用这个 client 调真实 API。

### OpenAICompatibleLLMClient.complete_json

【作用】  
调用 OpenAI-compatible `/chat/completions` 接口，并要求返回 JSON object。

【参数】  
同 `LLMClient.complete_json`。

【返回值】  
模型返回的 message content 字符串。

【执行流程】

1. 拼接 endpoint。
2. 构造请求 body。
3. 构造 HTTP POST request。
4. 发请求并解析响应 JSON。
5. 取 `choices[0].message.content`。
6. 网络或结构异常时抛 RuntimeError。

【逐行解释】

- `endpoint = self.settings.base_url.rstrip("/") + "/chat/completions"`: 去掉 base_url 尾部斜杠，再拼 API 路径。
- `body = {...}`: 构造 OpenAI chat completions 请求体。
- `"model": self.settings.model`: 使用配置模型。
- `"messages": [...]`: system/user 两条消息。
- `"temperature": 0.2`: 降低随机性。
- `"response_format": {"type": "json_object"}`: 请求模型返回 JSON object。
- `req = urlrequest.Request(...)`: 构造标准库 HTTP request。
- `data=json.dumps(...).encode("utf-8")`: JSON 序列化并编码为 bytes。
- `headers={...}`: 设置 Bearer token 和 content type。
- `method="POST"`: 使用 POST。
- `try:`: 捕获网络错误。
- `with urlrequest.urlopen(req, timeout=30) as response:`: 发请求，最多等 30 秒。
- `payload = json.loads(response.read().decode("utf-8"))`: 读取响应 bytes，解码并解析 JSON。
- `except URLError as exc:`: 捕获 URL/network 错误。
- `raise RuntimeError(...) from exc`: 抛更清楚的错误，并保留原异常链。
- `try: return str(payload["choices"][0]["message"]["content"])`: 取模型内容。
- `except (KeyError, IndexError, TypeError) as exc:`: 响应结构不符合预期时捕获。
- `raise RuntimeError(...) from exc`: 抛结构错误。

【涉及语法】

- `with` 上下文管理器。
- 标准库 HTTP。
- 异常链 `raise ... from exc`。
- 字典和列表索引。

【和项目整体流程的关系】

这是接入真实 LLM 的主要路径。输出仍会被 `_parse_json` 和 Pydantic 校验。

### ClaudeLLMClient.__init__ / complete_json

【作用】  
预留 Claude provider 接口，但当前未实现真实调用。

【参数】  
`settings` 和 `api_key`。

【返回值】  
`__init__` 无返回；`complete_json` 当前只抛异常。

【执行流程】  
保存配置；调用时抛 `RuntimeError`。

【逐行解释】

- `self.settings = settings`: 保存 Claude 配置。
- `self.api_key = api_key`: 保存 API key。
- `raise RuntimeError("Claude provider interface is reserved but not implemented in this MVP")`: 明确告诉调用方当前 MVP 未实现。

【涉及语法】

- stub 实现。
- 抛异常。

【和项目整体流程的关系】

如果配置成 claude 且有 key，调用会失败，然后 LLMTool 的 repair/fallback 机制会兜底。

### LLMTool.__init__

【作用】  
把 provider client、fallback client、启动警告封装成一个统一工具。

【参数】

- `client`: 主 LLM client。
- `fallback_client`: 兜底 client，默认 mock。
- `startup_warnings`: 启动阶段警告。

【返回值】  
无。

【逐行解释】

- `self.client = client`: 保存主 client。
- `self.fallback_client = fallback_client or MockLLMClient()`: 没传 fallback 就创建 mock。
- `self.startup_warnings = startup_warnings or []`: 没传警告就用空列表。

【涉及语法】

- `or` 默认值。
- 组合模式。

【和项目整体流程的关系】

Agent 不直接面对 provider，而是统一调用 LLMTool。

### LLMTool.provider_name

【作用】  
返回当前主 provider 名称。

【参数】  
无。

【返回值】  
字符串。

【逐行解释】

- `@property`: 把方法变成属性访问方式。
- `return self.client.provider_name`: 返回底层 client 的 provider 名。

【涉及语法】

- `@property` 装饰器。

【和项目整体流程的关系】

HealthCheck 用它判断是否 mock mode。

### LLMTool.summarize

【作用】  
生成文章摘要。

【参数】

- `article`
- `user_profile_snapshot`
- `skill_text`

【返回值】  
`SummaryLLMOutput`

【执行流程】

1. 构造 payload。
2. 调 `_generate_structured`。
3. 传入 summary schema、system prompt、fallback 逻辑。

【逐行解释】

- `payload = {"article": article, "user_profile_snapshot": user_profile_snapshot}`: 把文章和画像放进 prompt payload。
- `return self._generate_structured(...)`: 统一走结构化生成。
- `task="summary"`: 标明任务类型。
- `schema=SummaryLLMOutput`: 指定校验 schema。
- `system_prompt=(...)`: 告诉模型要生成中文知识摘要，并返回严格 JSON。
- `f"Skill:\n{skill_text}"`: 把 skill 文本拼进 system prompt。
- `payload=payload`: 把输入数据传给生成函数。
- `fallback=lambda issue: SummaryLLMOutput(...)`: 如果模型失败，用 fallback summary 生成结构化结果，并带 issue。

【涉及语法】

- lambda 匿名函数。
- 多行字符串拼接。
- Pydantic model 实例化。

【和项目整体流程的关系】

SummaryAgent 调用它，输出写入 `result["summary"]`。

### LLMTool.rewrite_post

【作用】  
把摘要改写成 Markdown 知识帖。

【参数】

- `article`
- `summary`
- `skill_text`

【返回值】  
`RewriteLLMOutput`

【执行流程】  
和 summarize 类似，但 task 是 `rewrite`，schema 是 `RewriteLLMOutput`，fallback 是模板 post。

【逐行解释】

- `payload = {"article": article, "summary": summary}`: 改写任务需要文章和摘要。
- `task="rewrite"`: 指定任务。
- `schema=RewriteLLMOutput`: 校验输出必须有 `post_text`。
- `system_prompt=...`: 要求模型避免标题党和营销语。
- `fallback=lambda issue: RewriteLLMOutput(...)`: 失败时用 mock 模板生成 post_text，并记录 issue。

【涉及语法】

- lambda。
- 多参数函数调用。

【和项目整体流程的关系】

RewriteAgent 调用它，输出最终会进入 MySQL `posts.markdown` 和 Markdown 文件。

### LLMTool.extract_feedback

【作用】  
从反馈中抽取情绪和偏好信号。

【参数】

- `feedback: list[JsonDict]`
- `skill_text`

【返回值】  
`FeedbackLLMOutput`

【执行流程】

1. 构造 `{"feedback": feedback}` payload。
2. 调 `_generate_structured`。
3. 要求输出 `sentiment`、`extracted_feedback`、`issues`。

【逐行解释】

- `payload = {"feedback": feedback}`: 反馈任务只需要 feedback 列表。
- `task="feedback"`: 指定任务。
- `schema=FeedbackLLMOutput`: 校验情绪必须是三选一。
- `system_prompt=...`: 要求从用户反馈抽取偏好信号。
- `fallback=lambda issue: self._fallback_feedback(feedback, issue)`: 失败时用 mock feedback fallback。

【涉及语法】

- 列表类型标注。
- lambda 调实例方法。

【和项目整体流程的关系】

FeedbackAgent 调用它，输出会被 MemoryAgent 用来更新用户画像。

### LLMTool._generate_structured

【作用】  
LLM 结构化输出核心函数。负责 prompt 序列化、调用 provider、JSON 解析、schema 校验、repair、fallback。

【参数】

- `task`
- `schema`
- `system_prompt`
- `payload`
- `fallback`

【返回值】  
对应 Pydantic schema 的实例。

【执行流程】

1. 把 payload 转 JSON 字符串。
2. 第一次调用 provider。
3. 解析 JSON 并校验 schema。
4. 如果失败，构造 repair prompt。
5. 第二次调用 provider。
6. 再解析校验。
7. 如果仍失败，调用 fallback。

【逐行解释】

- `user_prompt = json.dumps(payload, ensure_ascii=False)`: 把 payload 转成 JSON 字符串，保留中文。
- `try:`: 开始第一次尝试。
- `raw = self.client.complete_json(task, system_prompt, user_prompt)`: 调主 provider。
- `return _validate_schema(schema, _parse_json(raw))`: 先 parse JSON，再用 Pydantic 校验，成功就返回。
- `except Exception as first_error:`: 捕获第一次任何错误，包括网络、JSON、schema 错误。
- `LOGGER.warning(...)`: 记录警告。
- `try:`: 开始 repair 尝试。
- `repair_prompt = (...)`: 构造修复提示词。
- `f"Schema fields: {list(schema.model_fields.keys())}"`: 把 schema 字段名告诉模型。
- `f"Original payload: {user_prompt}"`: 带上原输入。
- `f"Previous error: {first_error}"`: 带上错误信息。
- `raw = self.client.complete_json(task, system_prompt, repair_prompt)`: 再调用同一个 provider。
- `return _validate_schema(schema, _parse_json(raw))`: 再解析和校验。
- `except Exception as repair_error:`: 修复也失败。
- `LOGGER.warning(...)`: 记录修复失败。
- `issue = f"llm_fallback:{self.client.provider_name}:{type(repair_error).__name__}"`: 构造机器可读 issue。
- `return fallback(issue)`: 调用兜底函数。

【涉及语法】

- 嵌套 `try/except`。
- 泛型类型 `type[SchemaT]`。
- 函数作为参数。
- f-string。
- Pydantic `model_fields`。

【和项目整体流程的关系】

这是 LLM 稳定性的关键。它保证 LLM 输出不稳定时，workflow 仍能返回结构化结果。

### LLMTool._fallback_summary

【作用】  
用 fallback client 生成摘要文本。

【参数】  
- `article`

【返回值】  
字符串 summary。

【逐行解释】

- `self.fallback_client.complete_json("summary", "", json.dumps({"article": article}, ensure_ascii=False))`: 用 fallback client 做 summary。
- `_parse_json(...)`: 解析 fallback 输出。
- `_validate_schema(SummaryLLMOutput, ...)`: 校验输出。
- `.summary`: 只取 summary 字段返回。

【涉及语法】

- 函数组合嵌套调用。
- 属性访问。

【和项目整体流程的关系】

主模型失败时，SummaryAgent 仍能拿到摘要。

### LLMTool._fallback_post

【作用】  
用 fallback client 生成 Markdown post。

【参数】  
- `article`
- `summary`

【返回值】  
字符串 post_text。

【逐行解释】

- 调 `fallback_client.complete_json("rewrite", ...)`: 用 mock rewrite。
- payload 包含 `article` 和 `summary`。
- parse JSON。
- 校验 `RewriteLLMOutput`。
- 返回 `.post_text`。

【涉及语法】  
嵌套函数调用和 Pydantic 校验。

【和项目整体流程的关系】  
保证 RewriteAgent 不会因为真实 LLM 坏输出而完全没有 post。

### LLMTool._fallback_feedback

【作用】  
用 fallback client 生成反馈抽取结果，并把 fallback issue 追加进去。

【参数】

- `feedback`
- `issue`

【返回值】  
`FeedbackLLMOutput`

【逐行解释】

- `output = _validate_schema(...)`: 用 fallback client 生成并校验 feedback 输出。
- `output.issues.append(issue)`: 把 fallback 原因加入 issues。
- `return output`: 返回结构化结果。

【涉及语法】

- 对 Pydantic model 的 list 字段追加元素。

【和项目整体流程的关系】

保证反馈闭环在 LLM 异常时仍能给 MemoryAgent 一个可用结果。

### build_llm_tool

【作用】  
根据 Settings 创建 LLMTool。

【参数】  
- `settings: Settings`

【返回值】  
`LLMTool`

【逐行解释】

- `client, warnings = build_llm_client(settings.llm)`: 创建底层 provider client，并拿到启动警告。
- `return LLMTool(client=client, startup_warnings=warnings)`: 包装成 LLMTool。

【涉及语法】  
元组解包。

【和项目整体流程的关系】  
`ArticleWorkflow.__init__` 用它创建统一 LLMTool。

### build_llm_client

【作用】  
根据 LLMSettings 选择具体 provider。

【参数】  
- `settings: LLMSettings`

【返回值】  
`tuple[LLMClient, list[str]]`: client 和 warning 列表。

【执行流程】

1. 标准化 provider 名。
2. provider 是 mock，返回 MockLLMClient。
3. provider 是 openai，检查 API key；没有 key fallback mock。
4. provider 是 claude，检查 API key；没有 key fallback mock；有 key 返回 stub client 并 warning。
5. 未知 provider fallback mock。

【逐行解释】

- `provider = settings.provider.strip().lower()`: 去空白并转小写。
- `warnings: list[str] = []`: 初始化警告列表。
- `if provider == "mock": return MockLLMClient(), warnings`: mock 直接返回。
- `if provider in {"openai", ...}:`: 支持多个 openai-compatible 名称。
- `api_key = os.getenv(settings.openai.api_key_env, "")`: 从环境变量读取 key。
- `if not api_key:`: 没 key。
- `message = f"Missing ..."`: 构造警告。
- `LOGGER.warning(message)`: 写日志。
- `warnings.append(message)`: 保存警告。
- `return MockLLMClient(), warnings`: fallback 到 mock。
- `return OpenAICompatibleLLMClient(settings.openai, api_key), warnings`: 有 key 则返回真实 client。
- `if provider == "claude":`: Claude 分支。
- 没 key 同样 fallback mock。
- 有 key 时返回 `ClaudeLLMClient`，但它是 stub，会在调用时抛异常。
- 未知 provider 构造 warning 并 fallback mock。

【涉及语法】

- 集合字面量。
- 环境变量读取。
- 多分支返回。

【和项目整体流程的关系】

决定 Summary/Rewrite/Feedback 最终使用 mock 还是真实 LLM。

### _parse_json

【作用】  
把 LLM 返回的字符串解析成 JSON object。

【参数】  
- `raw: str`

【返回值】  
`JsonDict`

【执行流程】

1. 去掉首尾空白。
2. 尝试直接 `json.loads`。
3. 如果失败，尝试截取第一个 `{` 到最后一个 `}`。
4. 要求最终结果必须是 dict。

【逐行解释】

- `text = raw.strip()`: 去掉空白。
- `try: value = json.loads(text)`: 直接解析。
- `except json.JSONDecodeError:`: JSON 解析失败。
- `start = text.find("{")`: 找第一个左大括号。
- `end = text.rfind("}")`: 找最后一个右大括号。
- `if start < 0 or end <= start: raise`: 没找到合法 JSON object 就重新抛出原错误。
- `value = json.loads(text[start : end + 1])`: 截出疑似 JSON 再解析。
- `if not isinstance(value, dict): raise ValueError(...)`: 只接受 JSON object，不接受数组或字符串。
- `return value`: 返回 dict。

【涉及语法】

- 字符串切片。
- `raise` 重新抛异常。
- `isinstance`。

【和项目整体流程的关系】

模型有时会在 JSON 前后加解释文字，这个函数做了轻量容错。

### _validate_schema

【作用】  
用 Pydantic schema 校验 JSON dict。

【参数】

- `schema`
- `value`

【返回值】  
schema 实例。

【逐行解释】

- `try: return schema.model_validate(value)`: 调 Pydantic 校验。
- `except ValidationError: raise`: 捕获后原样抛出，让上层 repair/fallback。

【涉及语法】

- 泛型 schema。
- Pydantic `model_validate`。

【和项目整体流程的关系】

保证 LLM 输出字段完整、类型正确。

### _load_prompt_payload

【作用】  
给 MockLLMClient 使用，把 user_prompt 解析回 dict。

【参数】  
- `user_prompt: str`

【返回值】  
`JsonDict`

【逐行解释】

- `try: value = json.loads(user_prompt)`: 尝试解析 JSON。
- `return value if isinstance(value, dict) else {}`: 如果是 dict 就返回，否则返回空 dict。
- `except json.JSONDecodeError: return {}`: 解析失败也返回空 dict。

【涉及语法】

- 条件表达式。
- 异常处理。

【和项目整体流程的关系】

让 mock provider 能读取传给 LLM 的 payload。

---

# python-agent/app/mcp/base_client.py

## 这个文件的整体作用

`base_client.py` 是 MCP 调用底座。它定义 transport 协议、mock transport、HTTP JSON-RPC transport、统一调用结果和统一 client 基类。所有具体 MCP client 都继承 `BaseMcpClient`。

## 它被谁调用

- `EmbeddingClient`
- `FetchClient`
- `MilvusClient`
- `Neo4jClient`
- `ArticleWorkflow.__init__` 创建 transport。

## 它调用了谁

- `MCPPolicy.check`
- `urllib.request` 发送 HTTP JSON-RPC
- 标准库 `json`、`time`、`uuid4`

## 重要类和函数列表

- `McpTransport.call`
- `McpCallResult`
- `MockMcpTransport.call`
- `MockMcpTransport._embedding`
- `JsonRpcMcpTransport.__init__`
- `JsonRpcMcpTransport.call`
- `JsonRpcMcpTransport._endpoint`
- `BaseMcpClient.__init__`
- `BaseMcpClient.call_tool`
- `BaseMcpClient._result`

## 函数逐个讲解

### McpTransport.call

【作用】  
定义 transport 必须提供的接口。

【参数】

- `server_name`
- `tool_name`
- `payload`

【返回值】  
`JsonDict`

【逐行解释】

- `class McpTransport(Protocol):`: Protocol 表示结构化接口，任何有 `call` 方法的对象都可以被当成 McpTransport。
- `def call(...) -> JsonDict:`: 规定方法签名。
- `...`: Python Ellipsis，占位，表示这里没有实现。

【涉及语法】

- `typing.Protocol`。
- Ellipsis。

【和项目整体流程的关系】

让 `BaseMcpClient` 可以同时接受 `MockMcpTransport` 和 `JsonRpcMcpTransport`。

### McpCallResult

【作用】  
统一 MCP 返回结构，包含业务结果和调用日志。

【参数】  
构造时需要:

- `result: JsonDict`
- `log: JsonDict`

【返回值】  
dataclass 实例。

【逐行解释】

- `@dataclass(slots=True)`: 自动生成构造函数；`slots=True` 减少动态属性。
- `result: JsonDict`: 工具返回结果。
- `log: JsonDict`: 审计日志。

【涉及语法】

- dataclass。
- slots。

【和项目整体流程的关系】

Agent 使用 `result` 做判断，GoFrame 使用 `log` 写入 `mcp_call_logs`。

### MockMcpTransport.call

【作用】  
进程内 mock MCP transport，不走 HTTP。

【参数】

- `server_name`
- `tool_name`
- `payload`

【返回值】  
mock 工具结果 dict。

【执行流程】

1. 根据 server_name 分支。
2. 根据 tool_name 返回固定或计算出的 mock 结果。
3. 未知 server 返回 `{"ok": True}`。

【逐行解释】

- `if server_name == "embedding-mcp":`: embedding server 分支。
- `if tool_name == "embed_batch":`: 批量 embedding。
- `embeddings = [self._embedding(str(text)) for text in payload.get("texts", [])]`: 列表推导式生成每个文本的向量。
- `return {"embeddings": embeddings, "dim": 3}`: 返回 3 维 mock 向量数组。
- `text = str(payload.get("text", ""))`: 单文本 embedding。
- `return {"embedding": self._embedding(text), "dim": 3}`: 返回单个向量。
- `if server_name == "milvus-mcp":`: Milvus mock 分支。
- `if tool_name == "semantic_deduplicate":`: 去重工具返回输入 items 和空 duplicates。
- `return {"matches": [{"article_id": "mock-related-1", "score": 0.81}]}`: 其他 Milvus 查询返回固定相似结果。
- `if server_name == "neo4j-mcp":`: Neo4j mock 分支。
- `if tool_name in {"update_profile", "update_user_interest_graph"}`: 更新类工具返回 updated。
- `return {"topics": [...], "user_id": ...}`: 查询类工具返回固定 topics。
- `if server_name == "fetch-mcp":`: fetch mock 分支。
- `if tool_name == "check_url_alive":`: 返回 URL 是否存在。
- `if tool_name == "extract_main_content":`: 把 html 当 raw_text 返回。
- `if tool_name == "clean_html":`: 简单移除 script 字符串。
- `return {"title": "Mock fetched document", ...}`: 其他 fetch 返回 mock 文档。
- `return {"ok": True}`: 未识别 server 的默认成功。

【涉及语法】

- 多层 `if`。
- 列表推导式。
- 集合包含判断 `in {...}`。

【和项目整体流程的关系】

默认 `MOCK_MCP=true` 时，FilterAgent 和 MemoryAgent 的 MCP 调用都走这里。

### MockMcpTransport._embedding

【作用】  
根据文本长度生成稳定的 3 维 mock embedding。

【参数】  
- `text: str`

【返回值】  
`list[float]`

【逐行解释】

- `return [round((len(text) % 13) / 13, 4), 0.37, 0.61]`: 第一维由文本长度决定，后两维固定。

【涉及语法】

- `len`。
- 取模 `%`。
- `round`。

【和项目整体流程的关系】

让向量搜索流程在没有真实 embedding 服务时仍能跑。

### JsonRpcMcpTransport.__init__

【作用】  
保存 MCP server endpoint 配置。

【参数】  
- `endpoints: dict[str, str]`

【逐行解释】

- `self.endpoints = endpoints`: 保存 URL 映射。

【和项目整体流程的关系】  
当 `MOCK_MCP=false` 时，ArticleWorkflow 会创建它。

### JsonRpcMcpTransport.call

【作用】  
通过 HTTP JSON-RPC 调用独立 MCP mock server。

【参数】

- `server_name`
- `tool_name`
- `payload`

【返回值】  
MCP tool 输出 dict。

【执行流程】

1. 找到 server URL。
2. 构造 JSON-RPC request。
3. POST 到 `/rpc`。
4. 解析 envelope。
5. 如果 envelope 有 error，抛 RuntimeError。
6. 如果 result.output 是 dict，返回 output。

【逐行解释】

- `base_url = self._endpoint(server_name).rstrip("/")`: 找 endpoint 并去掉尾部斜杠。
- `request_payload = {...}`: 构造 JSON-RPC 请求。
- `"jsonrpc": "2.0"`: JSON-RPC 协议版本。
- `"id": uuid4().hex`: 每次请求生成唯一 ID。
- `"method": "tools/call"`: 约定方法名。
- `"params": {"name": tool_name, "arguments": payload}`: 工具名和参数。
- `body = json.dumps(...).encode("utf-8")`: 序列化成 bytes。
- `req = urlrequest.Request(...)`: 构造 HTTP POST 请求。
- `with urlrequest.urlopen(req, timeout=8) as response:`: 发请求，超时 8 秒。
- `envelope = json.loads(response.read().decode("utf-8"))`: 解析响应。
- `if "error" in envelope:`: MCP server 返回错误。
- `message = envelope["error"].get("message", "MCP JSON-RPC error")`: 取错误消息。
- `raise RuntimeError(...)`: 抛异常给 BaseMcpClient 捕获。
- `result = envelope.get("result", {})`: 取 result。
- `if isinstance(result, dict) and isinstance(result.get("output"), dict): return result["output"]`: 兼容 MCP server 的 `{result: {output: ...}}`。
- `if isinstance(result, dict): return result`: 如果 result 本身就是 dict，也接受。
- `raise RuntimeError(...)`: 其他结构视为无效。

【涉及语法】

- UUID。
- HTTP request。
- JSON-RPC envelope。
- `isinstance`。

【和项目整体流程的关系】

它让 Python Agent 可以从进程内 mock 切换到独立 MCP mock server。

### JsonRpcMcpTransport._endpoint

【作用】  
根据 server_name 找对应 endpoint URL。

【参数】  
- `server_name`

【返回值】  
endpoint 字符串。

【逐行解释】

- `candidates = [...]`: 构造多个候选 key，比如 `embedding-mcp`、`embedding`、`embedding_mcp`。
- `for key in candidates:`: 遍历候选 key。
- `if self.endpoints.get(key): return self.endpoints[key]`: 找到配置就返回。
- `raise RuntimeError(...)`: 都找不到就报错。

【涉及语法】

- 字符串 `.replace`。
- 列表遍历。

【和项目整体流程的关系】

允许配置里使用 `embedding` 或 `embedding-mcp` 等不同 key。

### BaseMcpClient.__init__

【作用】  
保存 transport 和 policy。

【参数】

- `transport`
- `policy`

【逐行解释】

- `self.transport = transport`: 保存实际调用通道。
- `self.policy = policy or MCPPolicy()`: 如果没传 policy，则创建默认权限策略。

【涉及语法】  
`or` 默认值。

【和项目整体流程的关系】  
所有具体 MCP client 都继承它。

### BaseMcpClient.call_tool

【作用】  
MCP 调用核心函数: 构造请求、检查权限、调用 transport、捕获失败、生成日志。

【参数】

- `tool_name`
- `payload`
- `agent_name`
- `run_id`

【返回值】  
`McpCallResult`

【执行流程】

1. 记录开始时间。
2. 构造 JSON-RPC request payload。
3. 默认状态设为 failed。
4. 权限检查。
5. 如果权限拒绝，直接返回 denied 结果和日志。
6. 如果允许，调用 transport。
7. 成功则 status=success。
8. 异常则 status=failed。
9. 计算 latency。
10. 调 `_result` 包装。

【逐行解释】

- `started = time.perf_counter()`: 高精度计时开始。
- `request_payload = {...}`: 构造日志中的 JSON-RPC 请求。
- `success = False`: 默认未成功。
- `status = "failed"`: 默认状态 failed。
- `error_message = ""`: 默认无错误消息。
- `result: JsonDict`: 声明变量类型。
- `decision = self.policy.check(agent_name, tool_name)`: 权限检查。
- `if not decision.allowed:`: 如果不允许。
- `error_message = decision.error_message`: 保存权限错误。
- `result = {"error": {"code": "MCP_PERMISSION_DENIED", ...}}`: 构造标准错误结果。
- `response_payload = {...}`: 构造日志中的响应 JSON。
- `status = "denied"`: 状态为 denied。
- `latency_ms = int((time.perf_counter() - started) * 1000)`: 计算毫秒耗时。
- `return self._result(...)`: 返回统一结果，不调用 transport。
- `try:`: 开始真实调用。
- `result = self.transport.call(self.server_name, tool_name, payload)`: 调 transport。
- `response_payload = {"jsonrpc": "2.0", "result": result}`: 构造成功响应日志。
- `success = True`: 标记成功。
- `status = "success"`: 状态成功。
- `except Exception as exc:`: 捕获 transport 失败。
- `error_message = str(exc)`: 保存错误文本。
- `result = {"error": {"code": "MCP_CALL_FAILED", ...}}`: 构造失败结果。
- `response_payload = {"jsonrpc": "2.0", "error": ...}`: 构造失败响应日志。
- `status = "failed"`: 状态失败。
- `latency_ms = ...`: 计算耗时。
- `return self._result(...)`: 返回统一结构。

【涉及语法】

- keyword-only 参数: `*, agent_name, run_id` 表示后两个参数必须用关键字传。
- 高精度计时。
- 异常捕获。
- 统一返回对象。

【和项目整体流程的关系】

这是 MCP 稳定性和可观测性的核心。它保证失败或拒绝不会让 workflow 崩溃，而是变成结构化日志。

### BaseMcpClient._result

【作用】  
把 MCP 结果和日志封装成 `McpCallResult`。

【参数】  
包含 result、request_payload、response_payload、run_id、agent_name、tool_name、success、status、error_message、latency_ms。

【返回值】  
`McpCallResult`

【逐行解释】

- `return McpCallResult(...)`: 创建 dataclass 实例。
- `result=result`: 业务结果。
- `log={...}`: 日志字典。
- `"run_id": run_id`: 运行 ID。
- `"agent_name": agent_name`: 哪个 Agent 调用。
- `"server_name": self.server_name`: 哪个 MCP server。
- `"tool_name": tool_name`: 哪个工具。
- `"request_json": json.dumps(request_payload, ensure_ascii=False)`: 请求 JSON 字符串。
- `"response_json": json.dumps(response_payload, ensure_ascii=False)`: 响应 JSON 字符串。
- `"status": status`: success/failed/denied。
- `"error_message": error_message`: 错误消息。
- `"success": success`: 布尔成功标记。
- `"latency_ms": latency_ms`: 耗时。

【涉及语法】

- dataclass 构造。
- JSON 序列化。
- 字典字面量。

【和项目整体流程的关系】

返回的 `log` 会进入 gRPC response，GoFrame 再写入 MySQL `mcp_call_logs`。

---

# python-agent/app/mcp/policy.py

## 这个文件的整体作用

定义 MCP 工具权限矩阵，确保不同 Agent 只能调用自己允许的工具。

## 它被谁调用

- `BaseMcpClient.call_tool`
- 测试 `test_mcp_policy.py`

## 它调用了谁

不调用业务模块。

## 重要类和函数列表

- `MCPPermissionDecision`
- `MCPPolicy.__init__`
- `MCPPolicy.is_allowed`
- `MCPPolicy.check`
- `MCPPolicy.allowed_tools`
- `MCPPolicy._normalize_agent`

## 函数逐个讲解

### MCPPermissionDecision

【作用】  
表示一次权限检查结果。

【参数】  
- `allowed: bool`
- `error_message: str = ""`

【返回值】  
dataclass 实例。

【逐行解释】

- `@dataclass(frozen=True, slots=True)`: 不可变 dataclass，且使用 slots。
- `allowed: bool`: 是否允许。
- `error_message: str = ""`: 拒绝原因。

【涉及语法】  
dataclass、frozen、slots。

【和项目整体流程的关系】  
BaseMcpClient 根据它决定是否调用 transport。

### MCPPolicy.__init__

【作用】  
初始化权限矩阵。

【参数】  
- `permissions`: 可选自定义权限。

【逐行解释】

- `self._permissions = permissions or DEFAULT_AGENT_TOOL_PERMISSIONS`: 使用传入权限，否则使用默认矩阵。

【涉及语法】  
`or` 默认值。

【和项目整体流程的关系】  
默认矩阵约束 Filter/Memory 等 Agent 的 MCP 工具边界。

### MCPPolicy.is_allowed

【作用】  
返回布尔形式的权限检查结果。

【参数】  
- `agent_name`
- `tool_name`

【返回值】  
`bool`

【逐行解释】

- `return self.check(agent_name, tool_name).allowed`: 复用 `check`，只取 allowed 字段。

【涉及语法】  
方法复用、属性访问。

【和项目整体流程的关系】  
便于测试或简单判断。

### MCPPolicy.check

【作用】  
完整检查 agent 是否能调用 tool，并返回拒绝原因。

【参数】

- `agent_name`
- `tool_name`

【返回值】  
`MCPPermissionDecision`

【逐行解释】

- `agent = self._normalize_agent(agent_name)`: 标准化 Agent 名。
- `tool = str(tool_name).strip()`: 工具名转字符串并去空白。
- `if not agent:`: Agent 名为空。
- `return MCPPermissionDecision(False, "...missing agent...")`: 返回拒绝。
- `allowed_tools = self._permissions.get(agent)`: 查该 Agent 的允许工具集合。
- `if allowed_tools is None:`: 未知 Agent。
- `return MCPPermissionDecision(False, "...unknown agent...")`: 返回拒绝。
- `if tool not in allowed_tools:`: 工具不在 allowlist。
- `return MCPPermissionDecision(False, "...cannot call tool...")`: 返回拒绝。
- `return MCPPermissionDecision(True)`: 允许调用。

【涉及语法】

- 字典 `.get`。
- 集合 membership `in`。
- dataclass 实例化。

【和项目整体流程的关系】

防止比如 FilterAgent 调用不该调用的 fetch 工具。

### MCPPolicy.allowed_tools

【作用】  
返回某个 Agent 允许调用的工具集合。

【参数】  
- `agent_name`

【返回值】  
`set[str]`

【逐行解释】

- `self._normalize_agent(agent_name)`: 先标准化名字。
- `self._permissions.get(..., set())`: 查不到则返回空集合。
- `return set(...)`: 返回一个新集合，避免外部直接修改内部权限。

【涉及语法】  
集合构造。

【和项目整体流程的关系】  
可用于调试或展示工具权限。

### MCPPolicy._normalize_agent

【作用】  
标准化 Agent 名称。

【参数】  
- `agent_name`

【返回值】  
字符串。

【逐行解释】

- `str(agent_name or "")`: None 或空值转成空字符串。
- `.strip()`: 去掉首尾空白。
- `.lower()`: 转小写。
- `.replace("_agent", "")`: 去掉 `_agent` 后缀。
- `.replace(" agent", "")`: 去掉空格形式的 ` agent`。

【涉及语法】  
字符串链式调用。

【和项目整体流程的关系】  
让 `FilterAgent`、`filter_agent`、`filter agent` 都可以归一成 `filter`。

---

# python-agent/app/mcp/embedding_client.py

## 这个文件的整体作用

封装 embedding MCP 工具调用。

## 它被谁调用

- `FilterAgent.run`
- `MemoryAgent.run`

## 它调用了谁

- `BaseMcpClient.call_tool`

## 重要类和函数列表

- `EmbeddingClient.embed_text`
- `EmbeddingClient.embed_batch`

## 函数逐个讲解

### EmbeddingClient.embed_text

【作用】  
调用 `embedding-mcp` 的 `embed_text` 工具。

【参数】

- `text`
- `metadata`
- `agent_name`
- `run_id`

【返回值】  
`McpCallResult`

【逐行解释】

- `return self.call_tool("embed_text", {"text": text, "metadata": metadata or {}}, agent_name=agent_name, run_id=run_id)`: 调父类统一方法。`metadata or {}` 保证 metadata 为空时传空 dict。

【涉及语法】

- keyword-only 参数。
- `or` 默认 dict。

【和项目整体流程的关系】

FilterAgent 用它把文章转向量；MemoryAgent 用它把反馈转向量。

### EmbeddingClient.embed_batch

【作用】  
批量生成 embedding。

【参数】

- `texts`
- `metadata`
- `agent_name`
- `run_id`

【返回值】  
`McpCallResult`

【逐行解释】

- `return self.call_tool("embed_batch", {"texts": texts, "metadata": metadata or {}}, ...)`: 调统一 MCP 方法，工具名是 `embed_batch`。

【涉及语法】  
列表参数、字典 payload。

【和项目整体流程的关系】  
当前主流程暂未使用，但权限矩阵允许 FilterAgent 调用。

---

# python-agent/app/mcp/fetch_client.py

## 这个文件的整体作用

封装网页抓取、正文提取、HTML 清理、URL 存活检查等 MCP 工具。

## 它被谁调用

- `FilterAgent.run` 中有 fetch 分支，但默认 `EnableFetch=false`，且 filter 权限不允许 `fetch_webpage`。
- 未来 Summary/Check 可使用。

## 它调用了谁

- `BaseMcpClient.call_tool`

## 重要类和函数列表

- `fetch_url`
- `extract_main_content`
- `clean_html`
- `check_url_alive`

## 函数逐个讲解

### FetchClient.fetch_url

【作用】  
调用 `fetch_webpage` 抓网页。

【参数】  
- `url`
- `agent_name`
- `run_id`

【返回值】  
`McpCallResult`

【逐行解释】  
- `return self.call_tool("fetch_webpage", {"url": url}, ...)`: 把 URL 放进 payload，交给统一 MCP 调用。

【涉及语法】  
字典字面量、关键字参数。

【和项目整体流程的关系】  
当前默认文章链路不启用 fetch。

### FetchClient.extract_main_content

【作用】  
调用 `extract_main_content` 从 HTML 中提取正文。

【参数】  
- `html`
- `agent_name`
- `run_id`

【返回值】  
`McpCallResult`

【逐行解释】  
- `return self.call_tool("extract_main_content", {"html": html}, ...)`: 传 HTML 给 MCP 工具。

【和项目整体流程的关系】  
当前主流程未使用，skill 中给 SummaryAgent 预留。

### FetchClient.clean_html

【作用】  
调用 `clean_html` 清理 HTML。

【参数】  
- `html`
- `agent_name`
- `run_id`

【返回值】  
`McpCallResult`

【逐行解释】  
- `return self.call_tool("clean_html", {"html": html}, ...)`: 传 HTML 给清理工具。

【和项目整体流程的关系】  
当前主流程未使用。

### FetchClient.check_url_alive

【作用】  
调用 `check_url_alive` 检查 URL 是否可访问。

【参数】  
- `url`
- `agent_name`
- `run_id`

【返回值】  
`McpCallResult`

【逐行解释】  
- `return self.call_tool("check_url_alive", {"url": url}, ...)`: 传 URL 给 MCP。

【和项目整体流程的关系】  
`fact_check_skill.md` 设计中 CheckAgent 应该用它，但当前 CheckAgent 未实现。

---

# python-agent/app/mcp/milvus_client.py

## 这个文件的整体作用

封装 Milvus/向量记忆类 MCP 工具。当前实际服务是 mock 或内存模拟。

## 它被谁调用

- `FilterAgent.run` 使用 `search_similar_memory`。
- 当前 MemoryAgent 未调用 `insert_memory_vector`。

## 它调用了谁

- `BaseMcpClient.call_tool`

## 重要类和函数列表

- `search`
- `search_articles`
- `insert_memory_vector`
- `search_similar_memory`
- `semantic_deduplicate`

## 函数逐个讲解

### MilvusClient.search

【作用】  
调用 `search_related_articles`，根据 embedding 搜相关文章。

【参数】  
- `embedding`
- `limit`
- `agent_name`
- `run_id`

【返回值】  
`McpCallResult`

【逐行解释】  
- `return self.call_tool("search_related_articles", {"embedding": embedding, "limit": limit}, ...)`: 把向量和数量限制传给 MCP。

【和项目整体流程的关系】  
当前主流程没有直接使用这个函数。

### MilvusClient.search_articles

【作用】  
按 topic 搜文章。

【参数】  
- `topic`
- `limit`
- `agent_name`
- `run_id`

【返回值】  
`McpCallResult`

【逐行解释】  
- `return self.call_tool("search_articles", {"topic": topic, "limit": limit}, ...)`: 构造 topic 查询 payload。

【和项目整体流程的关系】  
Summary skill 中预留，但当前 SummaryAgent 未调用。

### MilvusClient.insert_memory_vector

【作用】  
插入或更新一条 memory vector。

【参数】

- `memory_id`
- `embedding`
- `metadata`
- `agent_name`
- `run_id`

【返回值】  
`McpCallResult`

【逐行解释】

- `return self.call_tool("insert_memory_vector", {...}, ...)`: 调统一 MCP。
- `"id": memory_id`: 记忆 ID。
- `"embedding": embedding`: 向量。
- `"metadata": metadata or {}`: 元数据默认空 dict。

【和项目整体流程的关系】  
`memory_update_skill.md` 中设计要用，但当前 MemoryAgent 没调用，所以反馈长期向量记忆还未落地。

### MilvusClient.search_similar_memory

【作用】  
搜索相似记忆。

【参数】  
- `embedding`
- `limit`
- `agent_name`
- `run_id`

【返回值】  
`McpCallResult`

【逐行解释】  
- `return self.call_tool("search_similar_memory", {"embedding": embedding, "limit": limit}, ...)`: 根据 embedding 查询相似 memory。

【和项目整体流程的关系】  
FilterAgent 默认会在 embedding 成功后调用它，命中后给文章加分。

### MilvusClient.semantic_deduplicate

【作用】  
按语义去重候选内容。

【参数】  
- `items`
- `threshold`
- `agent_name`
- `run_id`

【返回值】  
`McpCallResult`

【逐行解释】  
- `return self.call_tool("semantic_deduplicate", {"items": items, "threshold": threshold}, ...)`: 传入待去重 items 和阈值。

【和项目整体流程的关系】  
Check skill 中预留，但当前 CheckAgent 没调用。

---

# python-agent/app/mcp/neo4j_client.py

## 这个文件的整体作用

封装用户兴趣图相关 MCP 工具。当前 Neo4j 是 mock/内存模拟。

## 它被谁调用

- `FilterAgent.run` 调 `get_profile_context`。
- `MemoryAgent.run` 调 `update_profile`。

## 它调用了谁

- `BaseMcpClient.call_tool`

## 重要类和函数列表

- `get_profile_context`
- `update_profile`
- `get_related_topics`
- `explain_recommendation`

## 函数逐个讲解

### Neo4jClient.get_profile_context

【作用】  
查询用户兴趣图上下文。

【参数】

- `user_id`
- `snapshot`
- `agent_name`
- `run_id`

【返回值】  
`McpCallResult`

【逐行解释】

- `return self.call_tool("query_user_interest_graph", {...}, ...)`: 调兴趣图查询工具。
- `"user_id": user_id or "default-user"`: user_id 为空时用默认用户。
- `"snapshot": snapshot`: 把当前 MySQL snapshot 也传给 MCP。

【和项目整体流程的关系】  
FilterAgent 使用返回 topics 给文章加一点分。

### Neo4jClient.update_profile

【作用】  
更新用户兴趣图。

【参数】

- `snapshot`
- `extracted_feedback`
- `sentiment`
- `agent_name`
- `run_id`

【返回值】  
`McpCallResult`

【逐行解释】

- `return self.call_tool("update_user_interest_graph", {...}, ...)`: 调更新工具。
- `"user_id": str(snapshot.get("user_id", "default-user"))`: 从 snapshot 取用户 ID。
- `"snapshot": snapshot`: 传新画像。
- `"extracted_feedback": extracted_feedback`: 传反馈信号。
- `"sentiment": sentiment`: 传情绪。

【和项目整体流程的关系】  
MemoryAgent 调它记录兴趣图更新。当前是 mock，不是真实 Neo4j。

### Neo4jClient.get_related_topics

【作用】  
查询某主题相关主题。

【参数】  
- `topic`
- `limit`
- `agent_name`
- `run_id`

【返回值】  
`McpCallResult`

【逐行解释】  
- `return self.call_tool("get_related_topics", {"topic": topic, "limit": limit}, ...)`: 构造主题查询 payload。

【和项目整体流程的关系】  
当前主流程未使用，但 filter 权限允许它。

### Neo4jClient.explain_recommendation

【作用】  
解释某文章为什么被推荐。

【参数】

- `user_id`
- `article`
- `agent_name`
- `run_id`

【返回值】  
`McpCallResult`

【逐行解释】

- `return self.call_tool("explain_recommendation", {...}, ...)`: 调解释工具。
- `"user_id": user_id or "default-user"`: 默认用户兜底。
- `"article": article`: 传文章对象。

【和项目整体流程的关系】  
当前权限矩阵没有给 filter/memory 开这个工具，所以直接调用会被拒绝。主流程未使用。

---

# python-agent/app/mcp/__init__.py

## 这个文件的整体作用

集中导出 MCP 相关类，让其他文件可以从 `app.mcp` 一次性导入。

## 它被谁调用

- `python-agent/app/workflow/graph.py`
- 测试文件

## 它调用了谁

只做 import，不执行业务逻辑。

## 重要类和函数列表

无函数。主要是 `__all__`。

## 函数逐个讲解

### __all__

【作用】  
声明 `from app.mcp import *` 时导出的名字。

【参数】  
无。

【返回值】  
无。

【执行流程】  
文件加载时执行 import，并定义 `__all__` 列表。

【逐行解释】

- `from .base_client import ...`: 从同目录导入基础类。
- `from .embedding_client import EmbeddingClient`: 导入具体 client。
- `__all__ = [...]`: 列出公开 API。

【涉及语法】  
相对导入、模块公开接口。

【和项目整体流程的关系】  
让 `graph.py` 可以写简洁的 `from app.mcp import EmbeddingClient, ...`。

---

# goframe-backend/internal/handler/handler.go

## 这个文件的整体作用

GoFrame HTTP controller。它注册 HTTP 路由，接收请求，做基础参数校验，然后调用 `Harness` 业务编排。

## 它被谁调用

- `goframe-backend/main.go` 创建 Handler 并调用 `httpHandler.Register(server)`。

## 它调用了谁

- `harness.Harness`
- `store.Store`
- GoFrame `ghttp`

## 重要类和函数列表

- `Handler` struct
- `New`
- `Register`
- `Health`
- `RunArticles`
- `Feedback`
- `ListPosts`
- `ListRunLogs`
- `decodeJSON`
- `queryLimit`

## 函数逐个讲解

### New

【作用】  
创建 HTTP Handler。

【参数】

- `store *store.Store`
- `runner *harness.Harness`

【返回值】  
`*Handler`

【执行流程】  
把 store 和 harness 保存到 Handler。

【逐行解释】

- `func New(...) *Handler`: Go 函数，返回 Handler 指针。
- `return &Handler{store: store, harness: runner}`: 创建结构体并返回地址。

【涉及语法】

- Go 指针。
- 结构体字面量。

【和项目整体流程的关系】

main.go 用它把数据库层和业务编排层注入 HTTP controller。

### Register

【作用】  
注册 HTTP 路由。

【参数】  
- `server *ghttp.Server`

【返回值】  
无。

【逐行解释】

- `server.Group("/", func(group *ghttp.RouterGroup) { ... })`: 在根路径下注册一组路由。
- `group.GET("/health", h.Health)`: GET `/health` 对应 Health 方法。
- `group.POST("/runs/articles", h.RunArticles)`: POST `/runs/articles` 对应文章处理。
- `group.POST("/feedback", h.Feedback)`: POST `/feedback` 对应反馈处理。
- `group.GET("/posts", h.ListPosts)`: GET `/posts` 查询帖子。
- `group.GET("/run-logs", h.ListRunLogs)`: GET `/run-logs` 查询运行日志。

【涉及语法】

- Go 方法值 `h.Health`。
- 匿名函数。

【和项目整体流程的关系】

它把 README 中的 HTTP API 暴露出来。

### Health

【作用】  
检查 GoFrame、MySQL 和 Python Agent 状态。

【参数】  
- `r *ghttp.Request`

【返回值】  
通过 HTTP JSON 写出，不返回 Go 值。

【执行流程】

1. Ping MySQL。
2. 调 Python Agent HealthCheck。
3. 输出 JSON。

【逐行解释】

- `db := g.Map{"status": "ok"}`: 初始化 db 状态。
- `if err := h.store.Ping(r.Context()); err != nil { ... }`: Ping 数据库，失败则记录 unavailable。
- `agent := g.Map{"status": "ok"}`: 初始化 agent 状态。
- `if response, err := h.harness.AgentHealth(r.Context()); err != nil { ... } else { ... }`: 调 Python HealthCheck。
- `agent = g.Map{...}`: 成功时写入 Python status/version/enabled_agents/mock_mode。
- `r.Response.WriteJson(g.Map{...})`: 输出 JSON。

【涉及语法】

- Go `if init; condition` 写法。
- GoFrame `g.Map`。

【和项目整体流程的关系】

用于启动后确认 MySQL 和 Python Agent 是否可用。

### RunArticles

【作用】  
HTTP 触发完整文章处理流程。

【参数】  
- `r *ghttp.Request`

【返回值】  
HTTP JSON。

【逐行解释】

- `result := h.harness.RunArticles(r.Context())`: 调业务编排。当前接口不解析 body。
- `r.Response.WriteJson(g.Map{...})`: 返回 `ok` 和 result。
- `"ok": result.Status == "completed"`: 只有状态 completed 才算成功。

【涉及语法】

- 结构体方法调用。
- 比较表达式。

【和项目整体流程的关系】

这是文章链路的 HTTP controller 入口。

### Feedback

【作用】  
HTTP 触发反馈处理流程。

【参数】  
- `r *ghttp.Request`

【返回值】  
HTTP JSON。

【执行流程】

1. 解析 JSON body。
2. 校验 `post_id` 和 `feedback_text`。
3. 调 `Harness.ProcessFeedback`。
4. 返回结果。

【逐行解释】

- `var req harness.FeedbackRequest`: 声明请求结构体变量。
- `if !decodeJSON(r, &req) { return }`: 解析 JSON，失败则函数提前结束。
- `if req.PostID == "" || req.FeedbackText == "" { ... }`: 校验必填字段。
- `r.Response.WriteJson(g.Map{"ok": false, "error": ...})`: 校验失败返回错误。
- `result := h.harness.ProcessFeedback(r.Context(), req)`: 调反馈业务流程。
- `r.Response.WriteJson(g.Map{...})`: 返回结果。

【涉及语法】

- 取地址 `&req`。
- 逻辑或 `||`。
- 早返回。

【和项目整体流程的关系】

这是反馈闭环的 HTTP controller 入口。

### ListPosts

【作用】  
查询生成的 posts。

【参数】  
- `r *ghttp.Request`

【返回值】  
HTTP JSON。

【逐行解释】

- `posts, err := h.store.ListPosts(r.Context(), queryLimit(r))`: 查询数据库。
- `if err != nil { ... return }`: 出错返回 JSON error。
- `r.Response.WriteJson(g.Map{"ok": true, "items": posts})`: 成功返回列表。

【涉及语法】

- 多返回值。
- 错误处理。

【和项目整体流程的关系】

用于查看文章链路生成结果。

### ListRunLogs

【作用】  
查询运行日志。

【参数】  
- `r *ghttp.Request`

【返回值】  
HTTP JSON。

【逐行解释】

- `logs, err := h.store.ListRunLogs(...)`: 查 run_logs。
- 出错返回 `ok=false`。
- 成功返回 `items`。

【涉及语法】  
同 `ListPosts`。

【和项目整体流程的关系】  
用于调试 E2E 和查看每次 run 的 steps。

### decodeJSON

【作用】  
把 HTTP body 解析到目标结构体。

【参数】

- `r *ghttp.Request`
- `target any`

【返回值】  
`bool`: true 表示解析成功或无 body，false 表示失败且已写 response。

【逐行解释】

- `if r.Request.Body == nil { return true }`: 没有 body 时认为成功。
- `decoder := json.NewDecoder(r.Request.Body)`: 创建 JSON decoder。
- `if err := decoder.Decode(target); err != nil { ... }`: 解码到 target。
- `r.Response.WriteJson(...)`: 失败时写错误响应。
- `return false`: 告诉调用方不要继续。
- `return true`: 解码成功。

【涉及语法】

- `any` 是 Go 1.18+ 中 `interface{}` 的别名。
- JSON decoder。

【和项目整体流程的关系】

`Feedback` 使用它解析用户反馈请求。

### queryLimit

【作用】  
读取 URL query 中的 `limit` 参数。

【参数】  
- `r *ghttp.Request`

【返回值】  
`int`

【逐行解释】

- `limit, _ := strconv.Atoi(r.GetQuery("limit").String())`: 把 query 参数转 int，忽略错误。
- `if limit <= 0 { return 20 }`: 无效或未传则默认 20。
- `return limit`: 返回用户指定值。

【涉及语法】

- 多返回值忽略 `_`。
- 字符串转整数 `strconv.Atoi`。

【和项目整体流程的关系】

用于 `/posts` 和 `/run-logs` 分页限制。

---

# goframe-backend/internal/grpcclient/client.go

## 这个文件的整体作用

封装 GoFrame 到 Python Agent 的 gRPC client。它隐藏连接创建、关闭和 RPC 调用细节。

## 它被谁调用

- `goframe-backend/internal/logic/harness/harness.go`
  - `withArticlesClient`
  - `withFeedbackClient`
  - `AgentHealth`

## 它调用了谁

- 生成代码 `internal/agentpb`
- `google.golang.org/grpc`
- `credentials/insecure`

## 重要类和函数列表

- `Client` struct
- `New`
- `Close`
- `HealthCheck`
- `ProcessArticles`
- `ProcessFeedback`

## 函数逐个讲解

### New

【作用】  
创建 gRPC 连接和 AgentService client。

【参数】

- `ctx context.Context`
- `address string`
- `dialTimeout time.Duration`

【返回值】  
`(*Client, error)`

【执行流程】

1. 如果 timeout 无效，默认 5 秒。
2. 创建带超时的 dial context。
3. 使用 insecure credentials 连接 Python Agent。
4. 连接成功后创建 `agentpb.AgentServiceClient`。

【逐行解释】

- `if dialTimeout <= 0 { dialTimeout = 5 * time.Second }`: 没传 timeout 就用 5 秒。
- `dialCtx, cancel := context.WithTimeout(ctx, dialTimeout)`: 创建有超时的 context。
- `defer cancel()`: 函数返回时释放 context 资源。
- `conn, err := grpc.DialContext(...)`: 建立 gRPC 连接。
- `address`: Python Agent 地址，如 `127.0.0.1:50051`。
- `grpc.WithTransportCredentials(insecure.NewCredentials())`: 使用明文连接，不启用 TLS。适合本地 MVP。
- `grpc.WithBlock()`: 阻塞直到连接成功或超时。
- `if err != nil { return nil, err }`: 连接失败返回错误。
- `return &Client{conn: conn, service: agentpb.NewAgentServiceClient(conn)}, nil`: 创建封装 client。

【涉及语法】

- Go context。
- `defer`。
- 多返回值。
- 结构体指针。

【和项目整体流程的关系】

GoFrame 每次调用 Python Agent 前都会通过它创建 client。

### Close

【作用】  
关闭 gRPC 连接。

【参数】  
无。

【返回值】  
`error`

【逐行解释】

- `return c.conn.Close()`: 调底层连接关闭方法。

【涉及语法】  
方法转发。

【和项目整体流程的关系】  
Harness 中 `defer client.Close()` 保证 RPC 调用结束后释放连接。

### HealthCheck

【作用】  
调用 Python Agent 的 HealthCheck RPC。

【参数】  
- `ctx context.Context`

【返回值】  
`(*agentpb.HealthCheckResponse, error)`

【逐行解释】

- `return c.service.HealthCheck(ctx, &agentpb.HealthCheckRequest{Client: "goframe-backend"})`: 构造 request 并调用生成的 gRPC stub。

【涉及语法】

- 结构体字面量。
- 取地址。

【和项目整体流程的关系】

`/health` 用它检查 Python Agent 是否可用。

### ProcessArticles

【作用】  
调用 Python Agent 的文章处理 RPC。

【参数】

- `ctx`
- `request *agentpb.ProcessArticlesRequest`

【返回值】  
`(*agentpb.ProcessArticlesResponse, error)`

【逐行解释】

- `return c.service.ProcessArticles(ctx, request)`: 直接转发给生成的 gRPC client。

【涉及语法】  
方法封装。

【和项目整体流程的关系】  
这是 GoFrame 文章链路进入 Python Agent 的 RPC 调用点。

### ProcessFeedback

【作用】  
调用 Python Agent 的反馈处理 RPC。

【参数】

- `ctx`
- `request *agentpb.ProcessFeedbackRequest`

【返回值】  
`(*agentpb.ProcessFeedbackResponse, error)`

【逐行解释】

- `return c.service.ProcessFeedback(ctx, request)`: 直接转发给生成的 gRPC client。

【涉及语法】  
方法封装。

【和项目整体流程的关系】  
这是 GoFrame 反馈链路进入 Python Agent 的 RPC 调用点。

---

## 最后总结

按 README 主流程看，KnowMate 的函数调用有一个非常清晰的分界:

- GoFrame 负责 HTTP、RSS、MySQL、gRPC client 和 Markdown。
- Python Agent 负责 workflow、Agent、LLM 和 MCP。
- `graph.py` 是 Python Agent 的装配和调度中心。
- `agents/` 每个 Agent 都遵守 `run(state) -> state` 的模式。
- `llm_tool.py` 统一处理模型 provider、结构化输出和 fallback。
- `mcp/` 统一处理工具权限、transport、日志和失败降级。
- `handler.go` 是 HTTP controller，`grpcclient/client.go` 是 Go 侧调用 Python 的封装。

真正的数据主线是:

```text
文章: model.Article -> agentpb.Article -> Python state["articles"] -> state["article_results"] -> agentpb.ArticleProcessResult -> model.Post

反馈: FeedbackRequest -> feedback_logs -> agentpb.FeedbackItem -> Python state["feedback"] -> updated_profile_snapshot -> user_profile_snapshot
```
