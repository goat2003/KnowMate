from __future__ import annotations

from app.contracts import JsonDict
from app.mcp.base_client import BaseMcpClient, McpCallResult


class MilvusClient(BaseMcpClient):
    server_name = "milvus-mcp"

    def search(self, embedding: list[float], limit: int = 3, *, agent_name: str, run_id: str) -> McpCallResult:
        return self.call_tool("search_related_articles", {"embedding": embedding, "limit": limit}, agent_name=agent_name, run_id=run_id)

    def search_articles(self, topic: str = "", limit: int = 3, *, agent_name: str, run_id: str) -> McpCallResult:
        return self.call_tool("search_articles", {"topic": topic, "limit": limit}, agent_name=agent_name, run_id=run_id)

    def insert_memory_vector(
        self,
        memory_id: str,
        embedding: list[float],
        metadata: JsonDict | None = None,
        *,
        agent_name: str,
        run_id: str,
    ) -> McpCallResult:
        return self.call_tool(
            "insert_memory_vector",
            {"id": memory_id, "embedding": embedding, "metadata": metadata or {}},
            agent_name=agent_name,
            run_id=run_id,
        )

    def search_similar_memory(self, embedding: list[float], limit: int = 3, *, agent_name: str, run_id: str) -> McpCallResult:
        return self.call_tool("search_similar_memory", {"embedding": embedding, "limit": limit}, agent_name=agent_name, run_id=run_id)

    def semantic_deduplicate(self, items: list[JsonDict], threshold: float = 0.88, *, agent_name: str, run_id: str) -> McpCallResult:
        return self.call_tool("semantic_deduplicate", {"items": items, "threshold": threshold}, agent_name=agent_name, run_id=run_id)
