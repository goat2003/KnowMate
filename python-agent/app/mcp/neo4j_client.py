from __future__ import annotations

from app.contracts import JsonDict
from app.mcp.base_client import BaseMcpClient, McpCallResult


class Neo4jClient(BaseMcpClient):
    server_name = "neo4j-mcp"

    def get_profile_context(self, user_id: str, snapshot: JsonDict, *, agent_name: str, run_id: str) -> McpCallResult:
        return self.call_tool(
            "query_user_interest_graph",
            {"user_id": user_id or "default-user", "snapshot": snapshot},
            agent_name=agent_name,
            run_id=run_id,
        )

    def update_profile(
        self,
        snapshot: JsonDict,
        extracted_feedback: list[str],
        sentiment: str,
        *,
        agent_name: str,
        run_id: str,
    ) -> McpCallResult:
        return self.call_tool(
            "update_user_interest_graph",
            {
                "user_id": str(snapshot.get("user_id", "default-user")),
                "snapshot": snapshot,
                "extracted_feedback": extracted_feedback,
                "sentiment": sentiment,
            },
            agent_name=agent_name,
            run_id=run_id,
        )

    def get_related_topics(self, topic: str, limit: int = 5, *, agent_name: str, run_id: str) -> McpCallResult:
        return self.call_tool("get_related_topics", {"topic": topic, "limit": limit}, agent_name=agent_name, run_id=run_id)

    def explain_recommendation(self, user_id: str, article: JsonDict, *, agent_name: str, run_id: str) -> McpCallResult:
        return self.call_tool(
            "explain_recommendation",
            {"user_id": user_id or "default-user", "article": article},
            agent_name=agent_name,
            run_id=run_id,
        )
