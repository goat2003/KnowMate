from __future__ import annotations

from app.agents.base import BaseAgent
from app.contracts import JsonDict
from app.mcp.embedding_client import EmbeddingClient
from app.mcp.milvus_client import MilvusClient
from app.mcp.neo4j_client import Neo4jClient
from app.recommendation import RecommendationRanker, RecommendationSettings


class FilterAgent(BaseAgent):
    name = "filter"

    def __init__(
        self,
        skill_text: str = "",
        embedding_client: EmbeddingClient | None = None,
        milvus_client: MilvusClient | None = None,
        neo4j_client: Neo4jClient | None = None,
        recommendation_settings: RecommendationSettings | None = None,
    ) -> None:
        super().__init__(skill_text)
        self.embedding_client = embedding_client
        self.milvus_client = milvus_client
        self.neo4j_client = neo4j_client
        self.ranker = RecommendationRanker(recommendation_settings)

    def run(self, state: JsonDict) -> JsonDict:
        run_id = str(state.get("run_id", ""))
        profile = state.get("user_profile_snapshot", {})
        policy = state.get("mcp_policy", {})
        articles = list(state.get("articles", []))
        mcp_logs_by_article: dict[str, list[JsonDict]] = {}
        mcp_signals: dict[str, JsonDict] = {}

        for article in articles:
            article_id = str(article.get("article_id", ""))
            logs: list[JsonDict] = []
            signals: JsonDict = {}

            if policy.get("enable_neo4j") and self.neo4j_client:
                context = self.neo4j_client.get_profile_context(
                    str(profile.get("user_id", "")),
                    profile,
                    agent_name=self.name,
                    run_id=run_id,
                )
                logs.append(context.log)
                if context.result.get("topics"):
                    signals["neo4j_topics"] = context.result.get("topics")

            embedding: list[float] = []
            if policy.get("enable_embedding") and self.embedding_client:
                embedded = self.embedding_client.embed_text(
                    f"{article.get('title', '')}\n{article.get('raw_text', '')}",
                    agent_name=self.name,
                    run_id=run_id,
                )
                logs.append(embedded.log)
                embedding = list(embedded.result.get("embedding", []))

            if policy.get("enable_milvus") and embedding and self.milvus_client:
                related = self.milvus_client.search_similar_memory(
                    embedding,
                    minimum_score=self.ranker.settings.milvus_minimum_score,
                    agent_name=self.name,
                    run_id=run_id,
                )
                logs.append(related.log)
                if related.result.get("matches"):
                    signals["milvus_matches"] = related.result.get("matches")

            mcp_logs_by_article[article_id] = logs
            mcp_signals[article_id] = signals

        article_results = []
        for ranked in self.ranker.rank(articles, profile, mcp_signals=mcp_signals):
            article_results.append(
                {
                    "article": ranked.article,
                    "article_id": ranked.article_id,
                    "keep": ranked.keep,
                    "score": ranked.score,
                    "rank_position": ranked.rank_position,
                    "score_breakdown": ranked.score_breakdown,
                    "recommendation_reasons": ranked.recommendation_reasons,
                    "rejection_reasons": ranked.rejection_reasons,
                    "summary": "",
                    "post_text": "",
                    "check_pass": False,
                    "issues": ranked.issues,
                    "mcp_call_logs": mcp_logs_by_article.get(ranked.article_id, []),
                    "filter_reasons": ranked.recommendation_reasons + ranked.rejection_reasons,
                }
            )

        state["article_results"] = article_results
        return state
