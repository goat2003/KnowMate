"""English-only presentation helpers for retrieval outputs."""

from __future__ import annotations

import inspect
import re
from typing import Any, Callable, Optional

from app.retrieval.models import json_safe

Translator = Callable[..., Optional[str]]

_NON_ENGLISH_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def contains_non_english_script(text: Any) -> bool:
    return bool(_NON_ENGLISH_RE.search(str(text or "")))


class EnglishPresenter:
    """Render retrieval text while preserving source evidence terms."""

    def __init__(self, translator: Optional[Translator] = None) -> None:
        self.translator = translator

    def text(self, value: Any, context: str = "text", fallback: str = "") -> str:
        raw = self._normalize(value)
        if not raw:
            return fallback
        translated = self._translate(raw, context)
        if translated:
            return translated
        return raw

    def optional_text(self, value: Any, context: str = "text") -> str:
        return self.text(value, context=context, fallback="")

    def json_text(self, value: Any, context: str = "value") -> str:
        safe = json_safe(value)
        if safe in (None, "", [], {}):
            return "-"
        if isinstance(safe, (dict, list)):
            raw = self._json_dumps_ascii(safe)
        else:
            raw = str(safe)
        return self.text(raw, context=context, fallback="-")

    @staticmethod
    def placeholder(context: str) -> str:
        label = str(context or "text").replace("_", " ").strip() or "text"
        return f"[Non-English {label} omitted from external English output. Stable IDs are preserved for traceability.]"

    @staticmethod
    def _normalize(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (dict, list, tuple, set)):
            return EnglishPresenter._json_dumps_ascii(json_safe(value))
        return " ".join(str(value).split())

    @staticmethod
    def _json_dumps_ascii(value: Any) -> str:
        import json

        return json.dumps(value, ensure_ascii=True, sort_keys=True)

    def _translate(self, text: str, context: str) -> str:
        if self.translator is None:
            return ""
        try:
            candidate = self._call_translator(text, context)
        except Exception:
            return ""
        translated = self._normalize(candidate)
        if translated and not contains_non_english_script(translated):
            return translated
        return ""

    def _call_translator(self, text: str, context: str) -> Any:
        translator = self.translator
        if translator is None:
            return None
        try:
            signature = inspect.signature(translator)
        except (TypeError, ValueError):
            return translator(text, context)
        parameters = signature.parameters
        if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
            return translator(text, context=context)
        if "context" in parameters:
            return translator(text, context=context)
        positional = [
            param
            for param in parameters.values()
            if param.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        if len(positional) >= 2:
            return translator(text, context)
        return translator(text)
