from __future__ import annotations

from app.agents.base import BaseAgent
from app.config import Settings
from app.contracts import JsonDict
from app.tools import LLMTool, build_llm_tool


class FeedbackAgent(BaseAgent):
    name = "feedback"

    def __init__(self, skill_text: str = "", llm_tool: LLMTool | None = None) -> None:
        super().__init__(skill_text)
        self.llm_tool = llm_tool or build_llm_tool(Settings())

    def run(self, state: JsonDict) -> JsonDict:
        output = self.llm_tool.extract_feedback(list(state.get("feedback", [])), self.skill_text)
        state["sentiment"] = output.sentiment
        state["extracted_feedback"] = output.extracted_feedback
        if output.issues:
            state["feedback_issues"] = output.issues
        return state
