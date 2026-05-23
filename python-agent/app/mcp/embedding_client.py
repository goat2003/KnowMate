from __future__ import annotations

from app.contracts import JsonDict
from app.mcp.base_client import BaseMcpClient, McpCallResult


class EmbeddingClient(BaseMcpClient):
    server_name = "embedding-mcp"

    def embed_text(
        self,
        text: str,
        metadata: JsonDict | None = None,
        *,
        agent_name: str,
        run_id: str,
    ) -> McpCallResult:
        return self.call_tool("embed_text", {"text": text, "metadata": metadata or {}}, agent_name=agent_name, run_id=run_id)

    def embed_batch(
        self,
        texts: list[str],
        metadata: JsonDict | None = None,
        *,
        agent_name: str,
        run_id: str,
    ) -> McpCallResult:
        return self.call_tool(
            "embed_batch",
            {"texts": texts, "metadata": metadata or {}},
            agent_name=agent_name,
            run_id=run_id,
        )
