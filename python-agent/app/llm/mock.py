from __future__ import annotations

from app.contracts import JsonDict


class MockLLM:
    def summarize(self, article: JsonDict) -> str:
        title = article.get("title") or "Untitled"
        content = (article.get("content") or "").strip().replace("\n", " ")
        snippet = content[:160] if content else "No content was provided."
        return f"{title}: {snippet}"

    def rewrite_as_post(self, title: str, summary: str) -> str:
        return "\n".join(
            [
                f"# {title}",
                "",
                "## Summary",
                "",
                summary,
                "",
                "## Why it matters",
                "",
                "This mock draft highlights the core idea and leaves room for a real rewrite model.",
            ]
        )
