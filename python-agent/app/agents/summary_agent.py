from __future__ import annotations

from app.agents.base import BaseAgent
from app.contracts import JsonDict
from app.tools import LLMTool, build_llm_tool
from app.config import Settings


class SummaryAgent(BaseAgent):
    name = "summary"

    def __init__(self, skill_text: str = "", llm_tool: LLMTool | None = None) -> None:
        super().__init__(skill_text)
        self.llm_tool = llm_tool or build_llm_tool(Settings())

    def run(self, state: JsonDict) -> JsonDict:
        profile = dict(state.get("user_profile_snapshot", {}))
        for result in state.get("article_results", []):
            if not result.get("keep"):
                continue
            output = self.llm_tool.summarize(result["article"], profile, self.skill_text)
            result["summary"] = output.summary
            if output.issues:
                result.setdefault("issues", []).extend(output.issues)
        return state
