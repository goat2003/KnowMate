from __future__ import annotations

import os
from pathlib import Path
import sys


SERVER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(SERVER_DIR.parent / "common"))

from neo4j_store import (  # noqa: E402
    InterestGraphError,
    MemoryInterestGraphStore,
    Neo4jInterestGraphStore,
    normalize_interest_event,
)
from provider import ManagedProvider, ProviderUnavailableError, read_secret  # noqa: E402
from simple_http_mcp import ToolError, ToolSpec, require_object, require_str, run_server  # noqa: E402


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


def _mode() -> str:
    explicit = os.getenv("NEO4J_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    return "memory" if _bool_env("NEO4J_MOCK_MODE", True) else "neo4j"


MODE = _mode()
CONFIG = {
    "mode": MODE,
    "neo4j_uri": os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
    "neo4j_database": os.getenv("NEO4J_DATABASE", "neo4j"),
    "neo4j_user": os.getenv("NEO4J_USER", "neo4j"),
}


def _build_store():
    if MODE == "memory":
        return MemoryInterestGraphStore()
    if MODE != "neo4j":
        raise InterestGraphError(f"unsupported NEO4J_PROVIDER `{MODE}`")
    return Neo4jInterestGraphStore(
        uri=str(CONFIG["neo4j_uri"]),
        user=str(CONFIG["neo4j_user"]),
        password=read_secret("NEO4J_PASSWORD", os.getenv("NEO4J_PASSWORD_FILE", "")),
        database=str(CONFIG["neo4j_database"]),
    )


MANAGED = ManagedProvider(_build_store, mode=MODE)

TOPIC_SCHEMA = {
    "type": "object",
    "required": ["name"],
    "properties": {"name": {"type": "string"}, "weight": {"type": "number"}, "delta": {"type": "number"}},
    "additionalProperties": False,
}

TOOLS = [
    ToolSpec(
        name="query_user_interest_graph",
        description="Read ranked user interests from the configured graph store.",
        input_schema={
            "type": "object",
            "required": ["user_id"],
            "properties": {"user_id": {"type": "string"}, "limit": {"type": "integer"}, "snapshot": {"type": "object"}},
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["user_id", "topics"],
            "properties": {"user_id": {"type": "string"}, "topics": {"type": "array"}, "mock": {"type": "boolean"}},
        },
        examples=[{"request": {"user_id": "u1"}, "response": {"user_id": "u1", "topics": []}}],
    ),
    ToolSpec(
        name="update_user_interest_graph",
        description="Idempotently update user interests using a stable event ID.",
        input_schema={
            "type": "object",
            "required": ["user_id"],
            "properties": {
                "event_id": {"type": "string"},
                "user_id": {"type": "string"},
                "topics": {"type": "array", "items": TOPIC_SCHEMA},
                "snapshot": {"type": "object"},
                "extracted_feedback": {"type": "array", "items": {"type": "string"}},
                "sentiment": {"type": "string"},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["updated", "applied", "event_id", "topics"],
            "properties": {
                "updated": {"type": "boolean"},
                "applied": {"type": "boolean"},
                "event_id": {"type": "string"},
                "user_id": {"type": "string"},
                "topics": {"type": "array"},
                "mock": {"type": "boolean"},
            },
        },
        examples=[{"request": {"user_id": "u1", "event_id": "evt-1", "topics": [{"name": "AI", "weight": 0.1}]}, "response": {"updated": True, "applied": True}}],
    ),
    ToolSpec(
        name="get_related_topics",
        description="Return graph-related topics for a seed topic.",
        input_schema={
            "type": "object",
            "required": ["topic"],
            "properties": {"topic": {"type": "string"}, "limit": {"type": "integer"}},
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["topic", "topics"],
            "properties": {"topic": {"type": "string"}, "topics": {"type": "array"}, "mock": {"type": "boolean"}},
        },
        examples=[{"request": {"topic": "AI"}, "response": {"topic": "AI", "topics": []}}],
    ),
    ToolSpec(
        name="explain_recommendation",
        description="Explain a recommendation using user-interest and related-topic graph paths.",
        input_schema={
            "type": "object",
            "required": ["user_id", "article"],
            "properties": {"user_id": {"type": "string"}, "article": {"type": "object"}},
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["score", "reasons", "matched_topics", "related_paths"],
            "properties": {
                "score": {"type": "number"},
                "reasons": {"type": "array"},
                "matched_topics": {"type": "array"},
                "related_paths": {"type": "array"},
                "mock": {"type": "boolean"},
            },
        },
        examples=[{"request": {"user_id": "u1", "article": {"topics": ["AI"]}}, "response": {"score": 0.8, "reasons": []}}],
    ),
]


def _limit(payload: dict[str, object], default: int) -> int:
    return max(1, min(int(payload.get("limit", default) or default), 100))


def handle(tool: str, payload: dict[str, object]) -> dict[str, object]:
    try:
        store = MANAGED.get()
        if tool == "query_user_interest_graph":
            user_id = require_str(payload, "user_id")
            return {
                "user_id": user_id,
                "topics": store.query_user_interests(user_id, _limit(payload, 20)),  # type: ignore[attr-defined]
                "mock": MODE == "memory",
            }
        if tool == "update_user_interest_graph":
            return store.update_user_interests(normalize_interest_event(payload))  # type: ignore[attr-defined]
        if tool == "get_related_topics":
            topic = require_str(payload, "topic")
            return {
                "topic": topic,
                "topics": store.get_related_topics(topic, _limit(payload, 5)),  # type: ignore[attr-defined]
                "mock": MODE == "memory",
            }
        if tool == "explain_recommendation":
            return store.explain_recommendation(  # type: ignore[attr-defined]
                require_str(payload, "user_id"),
                require_object(payload, "article"),
            )
        raise ToolError(f"unknown tool `{tool}`", code=-32601)
    except ToolError:
        raise
    except (ProviderUnavailableError, InterestGraphError) as exc:
        raise ToolError(str(exc), data={"provider": MODE, "database": CONFIG["neo4j_database"]}) from exc


if __name__ == "__main__":
    run_server(
        "neo4j-mcp",
        int(os.getenv("PORT", "7004")),
        TOOLS,
        handle,
        CONFIG,
        health_provider=MANAGED.health,
        lifecycle=MANAGED,
    )
