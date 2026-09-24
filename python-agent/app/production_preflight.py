"""A real structured call must succeed before a production Agent starts serving."""
from app.config import Settings
from app.tools.llm_tool import build_llm_tool


def check_model(settings: Settings) -> None:
    if settings.environment not in {"prod", "production"}:
        return
    tool = build_llm_tool(settings)
    tool.summarize(
        {"title": "Startup probe", "content": "KnowMate checks its model before accepting work."},
        {},
        "Summarize the supplied text in a short sentence.",
    )
