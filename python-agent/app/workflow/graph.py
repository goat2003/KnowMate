from __future__ import annotations

from app.agents import CheckAgent, FeedbackAgent, FilterAgent, MemoryAgent, RewriteAgent, SummaryAgent
from app.config import Settings
from app.contracts import JsonDict, default_mcp_policy, ensure_run_id, normalize_article
from app.mcp import EmbeddingClient, FetchClient, JsonRpcMcpTransport, MCPPolicy, MilvusClient, MockMcpTransport, Neo4jClient
from app.skill_loader import load_skills
from app.tools import build_llm_tool
from app.workflow.state import AgentState


class ArticleWorkflow:
    def __init__(self, settings: Settings) -> None:
        skills = load_skills()
        transport = MockMcpTransport() if settings.mock_mcp else JsonRpcMcpTransport(settings.mcp_urls)
        mcp_policy = MCPPolicy()
        embedding_client = EmbeddingClient(transport, policy=mcp_policy)
        fetch_client = FetchClient(transport, policy=mcp_policy)
        milvus_client = MilvusClient(transport, policy=mcp_policy)
        neo4j_client = Neo4jClient(transport, policy=mcp_policy)
        llm_tool = build_llm_tool(settings)
        self.llm_tool = llm_tool

        self.filter_agent = FilterAgent(
            skills.get("filter_skill", ""),
            embedding_client=embedding_client,
            fetch_client=fetch_client,
            milvus_client=milvus_client,
            neo4j_client=neo4j_client,
        )
        self.summary_agent = SummaryAgent(skills.get("summary_skill", ""), llm_tool=llm_tool)
        self.rewrite_agent = RewriteAgent(skills.get("rewrite_post_skill", ""), llm_tool=llm_tool)
        self.check_agent = CheckAgent(skills.get("fact_check_skill", ""))
        self.feedback_agent = FeedbackAgent(skills.get("feedback_extract_skill", ""), llm_tool=llm_tool)
        self.memory_agent = MemoryAgent(
            skills.get("memory_update_skill", ""),
            embedding_client=embedding_client,
            neo4j_client=neo4j_client,
        )
        self._article_graph = self._try_build_article_langgraph()
        self._feedback_graph = self._try_build_feedback_langgraph()

    def process_articles(self, request: JsonDict) -> JsonDict:
        state: JsonDict = {
            "run_id": ensure_run_id(request.get("run_id")),
            "articles": [normalize_article(article) for article in request.get("articles", [])],
            "user_profile_snapshot": dict(request.get("user_profile_snapshot", {})),
            "mcp_policy": default_mcp_policy(request.get("mcp_policy", {})),
        }
        result = self._article_graph.invoke(state) if self._article_graph else self._run_article_sequential(state)
        return {
            "run_id": result["run_id"],
            "results": [
                {
                    "article_id": item.get("article_id", ""),
                    "keep": bool(item.get("keep", False)),
                    "score": float(item.get("score", 0)),
                    "summary": str(item.get("summary", "")),
                    "post_text": str(item.get("post_text", "")),
                    "check_pass": bool(item.get("check_pass", False)),
                    "issues": list(item.get("issues", [])),
                    "mcp_call_logs": list(item.get("mcp_call_logs", [])),
                }
                for item in result.get("article_results", [])
            ],
        }

    def process_feedback(self, request: JsonDict) -> JsonDict:
        state: JsonDict = {
            "run_id": ensure_run_id(request.get("run_id")),
            "feedback": list(request.get("feedback", [])),
            "user_profile_snapshot": dict(request.get("user_profile_snapshot", {})),
            "mcp_policy": default_mcp_policy(request.get("mcp_policy", {})),
            "mcp_call_logs": [],
        }
        result = self._feedback_graph.invoke(state) if self._feedback_graph else self._run_feedback_sequential(state)
        return {
            "run_id": result["run_id"],
            "sentiment": result.get("sentiment", "neutral"),
            "extracted_feedback": result.get("extracted_feedback", []),
            "updated_profile_snapshot": result.get("updated_profile_snapshot", {}),
            "mcp_call_logs": result.get("mcp_call_logs", []),
        }

    def enabled_agents(self) -> list[str]:
        return ["filter", "summary", "rewrite", "check", "feedback", "memory"]

    def _run_article_sequential(self, state: JsonDict) -> JsonDict:
        for agent in [
            self.filter_agent,
            self.summary_agent,
            self.rewrite_agent,
            self.check_agent,
        ]:
            state = agent.run(state)
        return state

    def _run_feedback_sequential(self, state: JsonDict) -> JsonDict:
        for agent in [self.feedback_agent, self.memory_agent]:
            state = agent.run(state)
        return state

    def _try_build_article_langgraph(self):
        try:
            from langgraph.graph import END, StateGraph
        except ImportError:
            return None

        graph = StateGraph(AgentState)
        graph.add_node("filter", self.filter_agent.run)
        graph.add_node("summary", self.summary_agent.run)
        graph.add_node("rewrite", self.rewrite_agent.run)
        graph.add_node("check", self.check_agent.run)

        graph.set_entry_point("filter")
        graph.add_edge("filter", "summary")
        graph.add_edge("summary", "rewrite")
        graph.add_edge("rewrite", "check")
        graph.add_edge("check", END)
        return graph.compile()

    def _try_build_feedback_langgraph(self):
        try:
            from langgraph.graph import END, StateGraph
        except ImportError:
            return None

        graph = StateGraph(AgentState)
        graph.add_node("feedback", self.feedback_agent.run)
        graph.add_node("memory", self.memory_agent.run)
        graph.set_entry_point("feedback")
        graph.add_edge("feedback", "memory")
        graph.add_edge("memory", END)
        return graph.compile()
