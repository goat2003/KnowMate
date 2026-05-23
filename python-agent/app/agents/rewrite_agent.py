from __future__ import annotations

from app.agents.base import BaseAgent
from app.config import Settings
from app.contracts import JsonDict
from app.tools import LLMTool, build_llm_tool


class RewriteAgent(BaseAgent):
    name = "rewrite"

    def __init__(self, skill_text: str = "", llm_tool: LLMTool | None = None) -> None:
        super().__init__(skill_text)
        self.llm_tool = llm_tool or build_llm_tool(Settings())

    def run(self, state: JsonDict) -> JsonDict:
        for result in state.get("article_results", []):
            if not result.get("keep"):
                continue
            output = self.llm_tool.rewrite_post(result["article"], str(result.get("summary", "")), self.skill_text)
            result["post_text"] = output.post_text
            if output.issues:
                result.setdefault("issues", []).extend(output.issues)
        return state
