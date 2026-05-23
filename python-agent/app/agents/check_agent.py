from __future__ import annotations

from app.agents.base import BaseAgent
from app.contracts import JsonDict


class CheckAgent(BaseAgent):
    name = "check"

    def run(self, state: JsonDict) -> JsonDict:
        for result in state.get("article_results", []):
            issues = list(result.get("issues", []))
            article = result.get("article", {})
            if not result.get("keep"):
                result["check_pass"] = False
                result["issues"] = issues
                continue
            if not result.get("summary"):
                issues.append("missing_summary")
            if not result.get("post_text"):
                issues.append("missing_post_text")
            if not article.get("url"):
                issues.append("missing_url")
            result["issues"] = issues
            result["check_pass"] = len(issues) == 0
        return state
