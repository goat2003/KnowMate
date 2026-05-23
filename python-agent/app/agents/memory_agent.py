from __future__ import annotations

from app.agents.base import BaseAgent
from app.contracts import JsonDict
from app.mcp.embedding_client import EmbeddingClient
from app.mcp.neo4j_client import Neo4jClient


class MemoryAgent(BaseAgent):
    name = "memory"

    def __init__(
        self,
        skill_text: str = "",
        embedding_client: EmbeddingClient | None = None,
        neo4j_client: Neo4jClient | None = None,
    ) -> None:
        super().__init__(skill_text)
        self.embedding_client = embedding_client
        self.neo4j_client = neo4j_client

    def run(self, state: JsonDict) -> JsonDict:
        run_id = str(state.get("run_id", ""))
        snapshot = dict(state.get("user_profile_snapshot", {}))
        extracted = list(state.get("extracted_feedback", []))
        sentiment = str(state.get("sentiment", "neutral"))
        logs = state.setdefault("mcp_call_logs", [])

        if self.embedding_client and state.get("mcp_policy", {}).get("enable_embedding"):
            embedded = self.embedding_client.embed_text(
                " ".join(extracted),
                {"source": "feedback"},
                agent_name=self.name,
                run_id=run_id,
            )
            logs.append(embedded.log)

        snapshot["last_feedback_sentiment"] = sentiment
        snapshot["feedback_count"] = str(int(snapshot.get("feedback_count", "0") or 0) + len(extracted))
        if extracted:
            snapshot["latest_feedback"] = " | ".join(extracted[-3:])

        if self.neo4j_client and state.get("mcp_policy", {}).get("enable_neo4j"):
            updated = self.neo4j_client.update_profile(snapshot, extracted, sentiment, agent_name=self.name, run_id=run_id)
            logs.append(updated.log)

        state["updated_profile_snapshot"] = snapshot
        return state
