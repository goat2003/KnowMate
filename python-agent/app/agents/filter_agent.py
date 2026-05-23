from __future__ import annotations

from app.agents.base import BaseAgent
from app.contracts import JsonDict
from app.mcp.embedding_client import EmbeddingClient
from app.mcp.fetch_client import FetchClient
from app.mcp.milvus_client import MilvusClient
from app.mcp.neo4j_client import Neo4jClient


class FilterAgent(BaseAgent):
    name = "filter"

    def __init__(
        self,
        skill_text: str = "",
        embedding_client: EmbeddingClient | None = None,
        fetch_client: FetchClient | None = None,
        milvus_client: MilvusClient | None = None,
        neo4j_client: Neo4jClient | None = None,
    ) -> None:
        super().__init__(skill_text)
        self.embedding_client = embedding_client
        self.fetch_client = fetch_client
        self.milvus_client = milvus_client
        self.neo4j_client = neo4j_client

    def run(self, state: JsonDict) -> JsonDict:
        run_id = str(state.get("run_id", ""))
        profile = state.get("user_profile_snapshot", {})
        policy = state.get("mcp_policy", {})
        article_results = []
        for article in state.get("articles", []):
            logs: list[JsonDict] = []
            if policy.get("enable_fetch") and not article.get("raw_text") and article.get("url") and self.fetch_client:
                fetched = self.fetch_client.fetch_url(article["url"], agent_name=self.name, run_id=run_id)
                logs.append(fetched.log)
                article["raw_text"] = str(fetched.result.get("raw_text", ""))

            score, reasons = self._score_article(article, profile)
            if policy.get("enable_neo4j") and self.neo4j_client:
                context = self.neo4j_client.get_profile_context(str(profile.get("user_id", "")), profile, agent_name=self.name, run_id=run_id)
                logs.append(context.log)
                if context.result.get("topics"):
                    score = min(score + 0.05, 1.0)
                    reasons.append("mock-profile-context")

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
                related = self.milvus_client.search_similar_memory(embedding, agent_name=self.name, run_id=run_id)
                logs.append(related.log)
                if related.result.get("matches"):
                    score = min(score + 0.05, 1.0)
                    reasons.append("mock-related-articles")

            keep = score >= 0.5 and bool(article.get("title"))
            article_results.append(
                {
                    "article": article,
                    "article_id": article["article_id"],
                    "keep": keep,
                    "score": round(score, 4),
                    "summary": "",
                    "post_text": "",
                    "check_pass": False,
                    "issues": [] if keep else ["filtered_out"],
                    "mcp_call_logs": logs,
                    "filter_reasons": reasons,
                }
            )
        state["article_results"] = article_results
        return state

    def _score_article(self, article: JsonDict, profile: JsonDict) -> tuple[float, list[str]]:
        title = str(article.get("title", "")).strip()
        raw_text = str(article.get("raw_text", "")).strip()
        haystack = f"{title} {raw_text}".lower()
        score = 0.1
        reasons: list[str] = []

        if title:
            score += 0.25
            reasons.append("has-title")
        if article.get("url"):
            score += 0.1
            reasons.append("has-url")
        if len(raw_text) >= 80:
            score += 0.25
            reasons.append("has-enough-text")
        elif raw_text:
            score += 0.12
            reasons.append("has-short-text")

        keywords = self._profile_keywords(profile)
        matched = [word for word in keywords if word and word.lower() in haystack]
        if matched:
            score += min(0.25, 0.08 * len(matched))
            reasons.append("matches-user-profile:" + ",".join(matched[:3]))

        return min(score, 1.0), reasons

    def _profile_keywords(self, profile: JsonDict) -> list[str]:
        values = []
        for key in ["interests", "topics", "keywords", "preferred_tags"]:
            raw = profile.get(key, "")
            if isinstance(raw, str):
                values.extend(part.strip() for part in raw.replace(";", ",").split(","))
            elif isinstance(raw, list):
                values.extend(str(part).strip() for part in raw)
        return [value for value in values if value]
