from __future__ import annotations

from app.mcp.base_client import BaseMcpClient, McpCallResult


class FetchClient(BaseMcpClient):
    server_name = "fetch-mcp"

    def fetch_url(self, url: str, *, agent_name: str, run_id: str) -> McpCallResult:
        return self.call_tool("fetch_webpage", {"url": url}, agent_name=agent_name, run_id=run_id)

    def extract_main_content(self, html: str, *, agent_name: str, run_id: str) -> McpCallResult:
        return self.call_tool("extract_main_content", {"html": html}, agent_name=agent_name, run_id=run_id)

    def clean_html(self, html: str, *, agent_name: str, run_id: str) -> McpCallResult:
        return self.call_tool("clean_html", {"html": html}, agent_name=agent_name, run_id=run_id)

    def check_url_alive(self, url: str, *, agent_name: str, run_id: str) -> McpCallResult:
        return self.call_tool("check_url_alive", {"url": url}, agent_name=agent_name, run_id=run_id)
