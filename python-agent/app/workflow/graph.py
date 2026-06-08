# 文件作用：
# 本文件负责组织 Python Agent Service 的核心文章处理和反馈处理工作流。
# 它把 GoFrame 后端通过 gRPC 传入的请求数据，转换为 Agent 可读写的 state，
# 再按“筛选 -> 总结 -> 改写 -> 校验”或“反馈提取 -> 记忆更新”的顺序交给不同 Agent 执行。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的工作流层，是 gRPC Server 与各个 Agent / LLM / MCP Client 之间的调度中心。
#
# 主要内容：
# 1. ArticleWorkflow 类：初始化技能提示词、MCP Client、LLM Tool 和各个 Agent。
# 2. process_articles 方法：处理文章请求，返回 GoFrame 可写入数据库和 Markdown 的结果。
# 3. process_feedback 方法：处理用户反馈，生成更新后的 user_profile_snapshot。
# 4. _try_build_article_langgraph / _try_build_feedback_langgraph：在安装 LangGraph 时构建图工作流。
# 5. _run_article_sequential / _run_feedback_sequential：在 LangGraph 不可用时按顺序执行兜底流程。
#
# 关键调用关系：
# - 被 app.grpc_server.AgentService 调用。
# - 调用 app.agents 下的 FilterAgent、SummaryAgent、RewriteAgent、CheckAgent、FeedbackAgent、MemoryAgent。
# - 调用 app.mcp 下的统一 MCP Client，通过 memory、stdio 或 Streamable HTTP 访问 MCP Server。
# - 调用 app.tools.build_llm_tool 创建 LLMTool，供 SummaryAgent、RewriteAgent、FeedbackAgent 使用。
#
# 初学者阅读建议：
# 建议先理解 AgentState 中有哪些字段，再看 process_articles 如何构造 state，
# 最后阅读各个 Agent 的 run 方法如何逐步补充 article_results、mcp_call_logs 和 updated_profile_snapshot。
from __future__ import annotations

from app.agents import CheckAgent, FeedbackAgent, FilterAgent, MemoryAgent, RewriteAgent, SummaryAgent
from app.config import McpServerSettings, Settings
from app.contracts import JsonDict, default_mcp_policy, ensure_run_id, normalize_article
from app.mcp import (
    EmbeddingClient,
    FetchClient,
    MCPPolicy,
    MemoryMcpTransport,
    MilvusClient,
    Neo4jClient,
    OfficialMcpTransport,
)
from app.skill_loader import load_skills
from app.tools import build_llm_tool
from app.workflow.state import AgentState


# 类作用：
# ArticleWorkflow 是 Python Agent Service 的核心工作流控制类。
# 它负责把配置、技能提示词、MCP 访问能力和 LLM 能力装配成可执行的 Agent 流程。
#
# 主要方法：
# - process_articles：处理 GoFrame 发来的文章列表，输出筛选、摘要、推文、校验和 MCP 调用日志。
# - process_feedback：处理用户反馈，输出情绪、偏好信号、更新后的用户画像快照和 MCP 调用日志。
# - _try_build_article_langgraph：构建文章处理 LangGraph 节点和边。
# - _try_build_feedback_langgraph：构建反馈处理 LangGraph 节点和边。
# - _run_article_sequential / _run_feedback_sequential：在未安装 LangGraph 时保持服务仍可运行。
class ArticleWorkflow:
    # 函数作用：
    # 初始化一次完整的 Agent 工作流运行环境。
    #
    # 参数说明：
    # - settings：从 config.yaml 和环境变量合并得到的服务配置，包含 LLM provider、MCP URL、mock 开关等。
    #
    # 返回值：
    # - 构造函数不返回值，但会在实例上保存各个 Agent、LLM Tool 和可选的 LangGraph 编译结果。
    #
    # 调用关系：
    # - 被 app.grpc_server.AgentService.__init__ 调用。
    # - 内部调用 load_skills、build_llm_tool，并创建各类 MCP Client。
    def __init__(self, settings: Settings) -> None:
        # 读取 app/skills 目录下的 Markdown 技能文件。
        # 这些文本会作为提示词规则传给对应 Agent，告诉 LLM 如何总结、改写、提取反馈等。
        skills = load_skills()
        # 每个 MCP Server 可独立选择 memory、stdio 或 Streamable HTTP。
        # 启动 transport 会初始化官方 SDK 会话并缓存 tools/list 结果。
        server_settings = settings.mcp_servers or _legacy_mcp_server_settings(settings)
        if all(config.transport == "memory" for config in server_settings.values()):
            transport = MemoryMcpTransport()
        else:
            transport = OfficialMcpTransport(server_settings, timeout_seconds=settings.mcp_timeout_seconds)
        transport.start()
        self.mcp_transport = transport
        fallback_transport = MemoryMcpTransport() if settings.mcp_memory_fallback else None
        client_options = {
            "max_retries": settings.mcp_max_retries,
            "retry_backoff_seconds": settings.mcp_retry_backoff_seconds,
            "circuit_failure_threshold": settings.mcp_circuit_failure_threshold,
            "circuit_reset_seconds": settings.mcp_circuit_reset_seconds,
            "fallback_transport": fallback_transport,
        }
        # MCPPolicy 负责限制“哪个 Agent 可以调用哪个 MCP Tool”。
        # 权限检查集中在 BaseMcpClient.call_tool 中执行，避免 Agent 绕过权限直接访问工具。
        mcp_policy = MCPPolicy()
        # EmbeddingClient 负责调用 embedding-mcp，将文章或反馈文本转换为向量。
        embedding_client = EmbeddingClient(transport, policy=mcp_policy, **client_options)
        # FetchClient 负责调用 fetch-mcp，在文章缺少正文时尝试按 URL 获取网页内容。
        fetch_client = FetchClient(transport, policy=mcp_policy, **client_options)
        # MilvusClient 负责调用 milvus-mcp，做向量检索、相似记忆查询和去重。
        milvus_client = MilvusClient(transport, policy=mcp_policy, **client_options)
        # Neo4jClient 负责调用 neo4j-mcp，读取或更新用户兴趣图谱。
        neo4j_client = Neo4jClient(transport, policy=mcp_policy, **client_options)
        # build_llm_tool 根据 settings.llm 选择 mock/openai/claude provider。
        # SummaryAgent、RewriteAgent、FeedbackAgent 都通过同一个 LLMTool 发起结构化 LLM 调用。
        llm_tool = build_llm_tool(settings)
        # 保存 LLMTool，HealthCheck 会读取 provider_name 判断当前是否处于 mock LLM 模式。
        self.llm_tool = llm_tool

        # FilterAgent 是文章流程的第一步。
        # 它会结合文章字段、用户画像、MCP 语义记忆和图谱上下文，决定文章是否继续进入总结流程。
        self.filter_agent = FilterAgent(
            skills.get("filter_skill", ""),
            embedding_client=embedding_client,
            milvus_client=milvus_client,
            neo4j_client=neo4j_client,
            recommendation_settings=settings.recommendation,
        )
        # SummaryAgent 调用 LLMTool，把保留下来的文章压缩成中文知识摘要。
        self.summary_agent = SummaryAgent(skills.get("summary_skill", ""), llm_tool=llm_tool, fetch_client=fetch_client)
        # RewriteAgent 调用 LLMTool，把摘要改写成适合发布或保存的推文/知识笔记文本。
        self.rewrite_agent = RewriteAgent(skills.get("rewrite_post_skill", ""), llm_tool=llm_tool)
        # CheckAgent 不调用 LLM，只做结果完整性校验，例如是否有摘要、推文和 URL。
        self.check_agent = CheckAgent(skills.get("fact_check_skill", ""))
        # FeedbackAgent 调用 LLMTool，从用户反馈中提取情绪和偏好信号。
        self.feedback_agent = FeedbackAgent(skills.get("feedback_extract_skill", ""), llm_tool=llm_tool)
        # MemoryAgent 根据反馈提取结果更新 user_profile_snapshot，并可调用 MCP 写入语义或图谱记忆。
        self.memory_agent = MemoryAgent(
            skills.get("memory_update_skill", ""),
            embedding_client=embedding_client,
            milvus_client=milvus_client,
            neo4j_client=neo4j_client,
        )
        # 尝试构建文章处理 LangGraph。
        # 如果运行环境未安装 langgraph，这里会得到 None，后续使用顺序执行兜底。
        self._article_graph = self._try_build_article_langgraph()
        # 尝试构建反馈处理 LangGraph，失败时同样回退到顺序执行。
        self._feedback_graph = self._try_build_feedback_langgraph()

    # 函数作用：
    # 处理一次文章任务请求，将 GoFrame/gRPC 入参转换为内部 state，
    # 交给 LangGraph 或顺序兜底流程执行，最后整理成 gRPC Response 易于填充的字典。
    #
    # 参数说明：
    # - request：普通字典形式的请求，包含 run_id、articles、user_profile_snapshot、mcp_policy。
    #
    # 返回值：
    # - 返回包含 run_id 和 results 的字典；results 中每项对应一篇文章的处理结果。
    #
    # 调用关系：
    # - 被 app.grpc_server.AgentService.ProcessArticles 调用。
    # - 内部调用 FilterAgent、SummaryAgent、RewriteAgent、CheckAgent。
    def process_articles(self, request: JsonDict) -> JsonDict:
        # 构造 AgentState 字典。LangGraph 和顺序流程都会在同一个 state 上追加字段。
        state: JsonDict = {
            # ensure_run_id 会在 GoFrame 没有传 run_id 时生成一个稳定格式的 run id，便于 run_logs 追踪。
            "run_id": ensure_run_id(request.get("run_id")),
            # 对每篇文章做字段标准化，确保后续 Agent 可以稳定读取 article_id、title、raw_text 等字段。
            "articles": [normalize_article(article) for article in request.get("articles", [])],
            # dict(...) 复制用户画像快照，避免 Agent 修改调用方传入的原始对象引用。
            "user_profile_snapshot": dict(request.get("user_profile_snapshot", {})),
            # 合并 MCP 默认策略和请求策略，决定本次运行是否启用 fetch/embedding/milvus/neo4j。
            "mcp_policy": default_mcp_policy(request.get("mcp_policy", {})),
        }
        # 优先使用 LangGraph 的 invoke 执行图工作流；如果 LangGraph 不存在，则按固定 Agent 顺序执行。
        result = self._article_graph.invoke(state) if self._article_graph else self._run_article_sequential(state)
        # 将内部 state 转成稳定的响应字典。
        # 这里显式做 bool/float/str/list 类型转换，避免 protobuf 填充时遇到 None 或非预期类型。
        return {
            "run_id": result["run_id"],
            "results": [
                {
                    # article_id 用于 GoFrame 后端把处理结果对应回 articles/posts 表记录。
                    "article_id": item.get("article_id", ""),
                    # keep 表示该文章是否通过 FilterAgent 筛选。
                    "keep": bool(item.get("keep", False)),
                    # score 是过滤阶段给出的相关性评分，GoFrame 可用于记录或展示排序依据。
                    "score": float(item.get("score", 0)),
                    # summary 来自 SummaryAgent 的 LLM 结构化输出。
                    "summary": str(item.get("summary", "")),
                    # post_text 来自 RewriteAgent 的 LLM 结构化输出。
                    "post_text": str(item.get("post_text", "")),
                    # check_pass 由 CheckAgent 设置，表示结果是否满足基本完整性要求。
                    "check_pass": bool(item.get("check_pass", False)),
                    # issues 累积过滤、LLM fallback、校验等阶段发现的问题。
                    "issues": list(item.get("issues", [])),
                    # mcp_call_logs 记录每次 MCP 工具调用的请求、响应、耗时和状态，用于写入 mcp_call_logs 表。
                    "mcp_call_logs": list(item.get("mcp_call_logs", [])),
                    "rank_position": int(item.get("rank_position", 0)),
                    "score_breakdown": list(item.get("score_breakdown", [])),
                    "recommendation_reasons": list(item.get("recommendation_reasons", [])),
                    "rejection_reasons": list(item.get("rejection_reasons", [])),
                }
                for item in result.get("article_results", [])
            ],
        }

    # 函数作用：
    # 处理用户反馈请求，从 feedback_logs 传来的反馈中提取偏好信号，并更新用户画像快照。
    #
    # 参数说明：
    # - request：普通字典形式的请求，包含 run_id、feedback、user_profile_snapshot、mcp_policy。
    #
    # 返回值：
    # - 返回情绪、提取出的反馈文本、更新后的 user_profile_snapshot 和 MCP 调用日志。
    #
    # 调用关系：
    # - 被 app.grpc_server.AgentService.ProcessFeedback 调用。
    # - 内部调用 FeedbackAgent 和 MemoryAgent。
    def process_feedback(self, request: JsonDict) -> JsonDict:
        # 构造反馈流程使用的 state；feedback 是列表，因为一次请求可能包含多条用户反馈。
        state: JsonDict = {
            # 确保反馈处理也有 run_id，便于把 run_logs、feedback_logs、mcp_call_logs 关联到同一次任务。
            "run_id": ensure_run_id(request.get("run_id")),
            # list(...) 复制反馈列表，避免下游修改请求对象本身。
            "feedback": list(request.get("feedback", [])),
            # 复制当前用户画像快照，MemoryAgent 会在副本上追加 last_feedback_sentiment 等字段。
            "user_profile_snapshot": dict(request.get("user_profile_snapshot", {})),
            # 权限策略决定 MemoryAgent 能否调用 embedding-mcp 或 neo4j-mcp。
            "mcp_policy": default_mcp_policy(request.get("mcp_policy", {})),
            # 反馈流程的 MCP 调用日志集中放在顶层 mcp_call_logs，最后会回传给 GoFrame 持久化。
            "mcp_call_logs": [],
        }
        # 优先走 LangGraph，否则使用顺序兜底，让缺少 langgraph 依赖的本地环境仍可运行。
        result = self._feedback_graph.invoke(state) if self._feedback_graph else self._run_feedback_sequential(state)
        # 返回 gRPC Server 需要的字段；缺失字段使用默认值，避免服务端响应构造失败。
        return {
            "run_id": result["run_id"],
            "sentiment": result.get("sentiment", "neutral"),
            "extracted_feedback": result.get("extracted_feedback", []),
            "structured_feedback": result.get("structured_feedback", {}),
            "profile_diff": result.get("profile_diff", {}),
            "updated_profile_snapshot": result.get("updated_profile_snapshot", {}),
            "mcp_call_logs": result.get("mcp_call_logs", []),
        }

    # 函数作用：
    # 返回当前工作流启用的 Agent 名称列表，供 HealthCheck 告诉 GoFrame 或运维侧服务能力。
    #
    # 参数说明：
    # - 无。
    #
    # 返回值：
    # - 返回字符串列表，每个值对应一个 Agent 的短名称。
    def enabled_agents(self) -> list[str]:
        return ["filter", "summary", "rewrite", "check", "feedback", "memory"]

    def close(self) -> None:
        self.mcp_transport.close()

    # 函数作用：
    # 在 LangGraph 不可用时顺序执行文章处理 Agent。
    #
    # 参数说明：
    # - state：文章处理共享状态，Agent 会读取并写回该字典。
    #
    # 返回值：
    # - 返回执行完四个 Agent 后的 state。
    #
    # 调用关系：
    # - 被 process_articles 在 self._article_graph 为 None 时调用。
    def _run_article_sequential(self, state: JsonDict) -> JsonDict:
        # 依次执行过滤、摘要、改写、校验。
        # 每个 Agent.run 都返回更新后的 state，下一步 Agent 继续使用同一份流程数据。
        for agent in [
            self.filter_agent,
            self.summary_agent,
            self.rewrite_agent,
            self.check_agent,
        ]:
            state = agent.run(state)
        return state

    # 函数作用：
    # 在 LangGraph 不可用时顺序执行反馈处理 Agent。
    #
    # 参数说明：
    # - state：反馈处理共享状态。
    #
    # 返回值：
    # - 返回执行完 FeedbackAgent 和 MemoryAgent 后的 state。
    def _run_feedback_sequential(self, state: JsonDict) -> JsonDict:
        # FeedbackAgent 先提取偏好信号，MemoryAgent 再用这些信号更新用户画像。
        for agent in [self.feedback_agent, self.memory_agent]:
            state = agent.run(state)
        return state

    # 函数作用：
    # 尝试构建文章处理 LangGraph，将每个 Agent 注册为图节点，并按固定边连接。
    #
    # 参数说明：
    # - 无。
    #
    # 返回值：
    # - 成功时返回可 invoke 的编译图；未安装 langgraph 时返回 None。
    #
    # 调用关系：
    # - 被 __init__ 调用。
    # - 返回值被 process_articles 使用。
    def _try_build_article_langgraph(self):
        # try/except 用于兼容未安装 LangGraph 的本地或 CI 环境。
        # ImportError 表示依赖缺失，此时服务不退出，而是启用顺序兜底流程。
        try:
            from langgraph.graph import END, StateGraph
        except ImportError:
            return None

        # StateGraph(AgentState) 声明图中共享 state 的字段结构，便于 LangGraph 在节点间传递数据。
        graph = StateGraph(AgentState)
        # add_node 把每个 Agent 的 run 方法注册为一个节点；节点名称也是调试时看到的流程名称。
        graph.add_node("filter", self.filter_agent.run)
        graph.add_node("summary", self.summary_agent.run)
        graph.add_node("rewrite", self.rewrite_agent.run)
        graph.add_node("check", self.check_agent.run)

        # 文章流程从 filter 开始，因为后续摘要和改写只应该处理通过筛选的文章。
        graph.set_entry_point("filter")
        # add_edge 定义节点执行顺序：filter 完成后进入 summary。
        graph.add_edge("filter", "summary")
        # summary 产生摘要后，rewrite 才能基于摘要生成推文。
        graph.add_edge("summary", "rewrite")
        # rewrite 生成 post_text 后，check 才能校验摘要、推文和 URL 是否完整。
        graph.add_edge("rewrite", "check")
        # END 表示图流程结束，compile 会生成可执行对象。
        graph.add_edge("check", END)
        return graph.compile()
    # 函数作用：
    # 尝试构建反馈处理 LangGraph，将反馈提取和记忆更新连接成图。
    #
    # 参数说明：
    # - 无。
    #
    # 返回值：
    # - 成功时返回可 invoke 的编译图；未安装 langgraph 时返回 None。
    def _try_build_feedback_langgraph(self):
        # 与文章图相同，LangGraph 是可选依赖；缺失时不影响核心服务启动。
        try:
            from langgraph.graph import END, StateGraph
        except ImportError:
            return None

        # 反馈流程复用 AgentState，因为它和文章流程共享 run_id、mcp_policy、mcp_call_logs 等字段。
        graph = StateGraph(AgentState)
        # feedback 节点负责把用户反馈转成结构化偏好信号。
        graph.add_node("feedback", self.feedback_agent.run)
        # memory 节点负责用偏好信号更新 user_profile_snapshot，并可写入 MCP 记忆系统。
        graph.add_node("memory", self.memory_agent.run)
        # 反馈流程必须先提取信息，再更新记忆。
        graph.set_entry_point("feedback")
        graph.add_edge("feedback", "memory")
        # memory 完成后流程结束，结果会包含 updated_profile_snapshot。
        graph.add_edge("memory", END)
        return graph.compile()


def _legacy_mcp_server_settings(settings: Settings) -> dict[str, McpServerSettings]:
    if settings.mock_mcp:
        return {
            name: McpServerSettings(transport="memory")
            for name in ["embedding-mcp", "fetch-mcp", "milvus-mcp", "neo4j-mcp"]
        }
    servers: dict[str, McpServerSettings] = {}
    for name, url in settings.mcp_urls.items():
        server_name = name if name.endswith("-mcp") else f"{name}-mcp"
        servers[server_name] = McpServerSettings(transport="streamable_http", url=url)
    return servers
