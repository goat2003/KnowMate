from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    run_id: str
    articles: list[dict[str, Any]]
    feedback: list[dict[str, Any]]
    user_profile_snapshot: dict[str, str]
    mcp_policy: dict[str, Any]
    article_results: list[dict[str, Any]]
    sentiment: str
    extracted_feedback: list[str]
    updated_profile_snapshot: dict[str, str]
    mcp_call_logs: list[dict[str, Any]]
