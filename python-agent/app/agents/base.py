from __future__ import annotations

from app.contracts import JsonDict


class BaseAgent:
    name = "base"

    def __init__(self, skill_text: str = "") -> None:
        self.skill_text = skill_text

    def run(self, state: JsonDict) -> JsonDict:
        raise NotImplementedError
