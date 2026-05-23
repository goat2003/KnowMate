from __future__ import annotations

from dataclasses import dataclass


DEFAULT_AGENT_TOOL_PERMISSIONS: dict[str, set[str]] = {
    "filter": {
        "embed_text",
        "embed_batch",
        "search_similar_memory",
        "query_user_interest_graph",
        "get_related_topics",
    },
    "summary": {
        "fetch_webpage",
        "extract_main_content",
        "search_articles",
    },
    "check": {
        "fetch_webpage",
        "check_url_alive",
        "search_similar_memory",
        "semantic_deduplicate",
    },
    "feedback": {
        "embed_text",
        "search_similar_memory",
    },
    "memory": {
        "embed_text",
        "insert_memory_vector",
        "search_similar_memory",
        "update_user_interest_graph",
        "query_user_interest_graph",
        "get_related_topics",
    },
    "output": {
        "save_markdown",
        "generate_daily_report",
        "generate_weekly_report",
        "send_email",
    },
}


@dataclass(frozen=True, slots=True)
class MCPPermissionDecision:
    allowed: bool
    error_message: str = ""


class MCPPolicy:
    def __init__(self, permissions: dict[str, set[str]] | None = None) -> None:
        self._permissions = permissions or DEFAULT_AGENT_TOOL_PERMISSIONS

    def is_allowed(self, agent_name: str, tool_name: str) -> bool:
        return self.check(agent_name, tool_name).allowed

    def check(self, agent_name: str, tool_name: str) -> MCPPermissionDecision:
        agent = self._normalize_agent(agent_name)
        tool = str(tool_name).strip()
        if not agent:
            return MCPPermissionDecision(False, f"MCP permission denied: missing agent for tool `{tool}`")
        allowed_tools = self._permissions.get(agent)
        if allowed_tools is None:
            return MCPPermissionDecision(False, f"MCP permission denied: unknown agent `{agent}`")
        if tool not in allowed_tools:
            return MCPPermissionDecision(
                False,
                f"MCP permission denied: agent `{agent}` cannot call tool `{tool}`",
            )
        return MCPPermissionDecision(True)

    def allowed_tools(self, agent_name: str) -> set[str]:
        return set(self._permissions.get(self._normalize_agent(agent_name), set()))

    def _normalize_agent(self, agent_name: str) -> str:
        return str(agent_name or "").strip().lower().replace("_agent", "").replace(" agent", "")
