from __future__ import annotations

import os
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "common"))

from simple_http_mcp import ToolError, ToolSpec, require_object, require_str, run_server  # noqa: E402


CONFIG = {
    "mock_mode": os.getenv("NEO4J_MOCK_MODE", "true").lower() != "false",
    "neo4j_uri": os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
    "neo4j_database": os.getenv("NEO4J_DATABASE", "neo4j"),
}

USER_GRAPH: dict[str, dict[str, float]] = {
    "default-user": {"AI": 0.91, "knowledge-management": 0.84, "engineering": 0.72}
}

TOOLS = [
    ToolSpec(
        name="query_user_interest_graph",
        description="Read a mock user interest graph.",
        input_schema={"type": "object", "required": ["user_id"], "properties": {"user_id": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"user_id": {"type": "string"}, "topics": {"type": "array"}}},
        examples=[{"request": {"user_id": "default-user"}, "response": {"topics": [{"name": "AI", "weight": 0.91}]}}],
    ),
    ToolSpec(
        name="update_user_interest_graph",
        description="Update mock user interest weights from feedback signals.",
        input_schema={"type": "object", "required": ["user_id", "topics"], "properties": {"user_id": {"type": "string"}, "topics": {"type": "array"}}},
        output_schema={"type": "object", "properties": {"updated": {"type": "boolean"}, "topics": {"type": "array"}}},
        examples=[{"request": {"user_id": "default-user", "topics": [{"name": "AI", "weight": 0.1}]}, "response": {"updated": True}}],
    ),
    ToolSpec(
        name="get_related_topics",
        description="Return mock related topics for one seed topic.",
        input_schema={"type": "object", "required": ["topic"], "properties": {"topic": {"type": "string"}, "limit": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {"topics": {"type": "array"}}},
        examples=[{"request": {"topic": "AI"}, "response": {"topics": [{"name": "agents", "score": 0.86}]}}],
    ),
    ToolSpec(
        name="explain_recommendation",
        description="Explain why an article matches the mock user graph.",
        input_schema={"type": "object", "required": ["user_id", "article"], "properties": {"user_id": {"type": "string"}, "article": {"type": "object"}}},
        output_schema={"type": "object", "properties": {"reasons": {"type": "array"}, "score": {"type": "number"}}},
        examples=[{"request": {"user_id": "default-user", "article": {"title": "AI workflow"}}, "response": {"score": 0.91}}],
    ),
]


ALIASES = {
    "query_profile_context": "query_user_interest_graph",
    "update_profile": "update_user_interest_graph",
}


def handle(tool: str, payload: dict[str, object]) -> dict[str, object]:
    tool = ALIASES.get(tool, tool)
    if tool == "query_user_interest_graph":
        return _query_user_interest_graph(payload)
    if tool == "update_user_interest_graph":
        return _update_user_interest_graph(payload)
    if tool == "get_related_topics":
        return _get_related_topics(payload)
    if tool == "explain_recommendation":
        return _explain_recommendation(payload)
    raise ToolError(f"unknown tool `{tool}`", code=-32601)


def _query_user_interest_graph(payload: dict[str, object]) -> dict[str, object]:
    user_id = require_str(payload, "user_id", "default-user") or "default-user"
    snapshot = payload.get("snapshot", {})
    if isinstance(snapshot, dict):
        _merge_snapshot(user_id, snapshot)
    topics = _topics(user_id)
    return {"user_id": user_id, "topics": topics, "mock": CONFIG["mock_mode"]}


def _update_user_interest_graph(payload: dict[str, object]) -> dict[str, object]:
    user_id = str(payload.get("user_id") or "default-user")
    if "snapshot" in payload:
        snapshot = require_object(payload, "snapshot")
        _merge_snapshot(user_id, snapshot)
    for topic in payload.get("topics", []) if isinstance(payload.get("topics", []), list) else []:
        if isinstance(topic, dict):
            name = str(topic.get("name", "")).strip()
            weight = float(topic.get("weight", 0.1) or 0.1)
            if name:
                USER_GRAPH.setdefault(user_id, {})[name] = min(1.0, max(0.0, USER_GRAPH.setdefault(user_id, {}).get(name, 0.0) + weight))
    for feedback in payload.get("extracted_feedback", []) if isinstance(payload.get("extracted_feedback", []), list) else []:
        text = str(feedback)
        for candidate in ["AI", "knowledge-management", "engineering", "workflow", "summary"]:
            if candidate.lower() in text.lower():
                USER_GRAPH.setdefault(user_id, {})[candidate] = min(1.0, USER_GRAPH.setdefault(user_id, {}).get(candidate, 0.4) + 0.05)
    return {"updated": True, "user_id": user_id, "topics": _topics(user_id), "mock": CONFIG["mock_mode"]}


def _get_related_topics(payload: dict[str, object]) -> dict[str, object]:
    topic = require_str(payload, "topic")
    limit = max(1, min(int(payload.get("limit", 5) or 5), 20))
    related_map = {
        "AI": ["agents", "LLM", "workflow", "evaluation", "retrieval"],
        "knowledge-management": ["PKM", "graph", "memory", "summarization", "taxonomy"],
        "engineering": ["testing", "observability", "architecture", "automation", "reliability"],
    }
    related = related_map.get(topic, ["AI", "knowledge-management", "engineering", "workflow", "memory"])
    return {"topic": topic, "topics": [{"name": name, "score": round(0.9 - idx * 0.06, 4)} for idx, name in enumerate(related[:limit])], "mock": CONFIG["mock_mode"]}


def _explain_recommendation(payload: dict[str, object]) -> dict[str, object]:
    user_id = require_str(payload, "user_id", "default-user") or "default-user"
    article = require_object(payload, "article")
    text = f"{article.get('title', '')} {article.get('summary', '')} {article.get('raw_text', '')}".lower()
    reasons = []
    score = 0.0
    for topic, weight in USER_GRAPH.get(user_id, USER_GRAPH["default-user"]).items():
        if topic.lower() in text:
            reasons.append(f"matched user topic `{topic}`")
            score = max(score, weight)
    if not reasons:
        reasons.append("no direct topic match; returned baseline recommendation")
        score = 0.35
    return {"user_id": user_id, "score": round(score, 4), "reasons": reasons, "mock": CONFIG["mock_mode"]}


def _merge_snapshot(user_id: str, snapshot: dict[str, object]) -> None:
    interests = str(snapshot.get("interests", ""))
    for raw in interests.replace(";", ",").split(","):
        topic = raw.strip()
        if topic:
            USER_GRAPH.setdefault(user_id, {})[topic] = max(USER_GRAPH.setdefault(user_id, {}).get(topic, 0.0), 0.7)


def _topics(user_id: str) -> list[dict[str, object]]:
    graph = USER_GRAPH.setdefault(user_id, dict(USER_GRAPH["default-user"]))
    return [{"name": name, "weight": round(weight, 4)} for name, weight in sorted(graph.items(), key=lambda item: item[1], reverse=True)]


if __name__ == "__main__":
    run_server("neo4j-mcp", int(os.getenv("PORT", "7004")), TOOLS, handle, CONFIG)
