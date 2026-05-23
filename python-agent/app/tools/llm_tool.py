from __future__ import annotations

from abc import ABC, abstractmethod
import json
import logging
import os
from typing import Any, Literal, TypeVar
from urllib import request as urlrequest
from urllib.error import URLError

from pydantic import BaseModel, Field, ValidationError

from app.config import ClaudeSettings, LLMSettings, OpenAISettings, Settings
from app.contracts import JsonDict


LOGGER = logging.getLogger(__name__)
SchemaT = TypeVar("SchemaT", bound=BaseModel)


class SummaryLLMOutput(BaseModel):
    summary: str = Field(min_length=1)
    issues: list[str] = Field(default_factory=list)


class RewriteLLMOutput(BaseModel):
    post_text: str = Field(min_length=1)
    issues: list[str] = Field(default_factory=list)


class FeedbackLLMOutput(BaseModel):
    sentiment: Literal["positive", "neutral", "negative"] = "neutral"
    extracted_feedback: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class LLMClient(ABC):
    provider_name = "base"

    @abstractmethod
    def complete_json(self, task: str, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError


class MockLLMClient(LLMClient):
    provider_name = "mock"

    def complete_json(self, task: str, system_prompt: str, user_prompt: str) -> str:
        payload = _load_prompt_payload(user_prompt)
        if task == "summary":
            article = payload.get("article", {})
            title = str(article.get("title") or "未命名文章")
            raw_text = str(article.get("raw_text") or "")
            compact = " ".join(raw_text.replace("\r", " ").replace("\n", " ").split())
            snippet = compact[:180] + ("..." if len(compact) > 180 else "")
            if not snippet:
                snippet = "原文内容较少，当前只能基于标题生成占位摘要。"
            return json.dumps({"summary": f"这篇文章《{title}》主要讨论：{snippet}", "issues": []}, ensure_ascii=False)
        if task == "rewrite":
            article = payload.get("article", {})
            title = str(article.get("title") or "知识笔记")
            summary = str(payload.get("summary") or "")
            post_text = "\n".join(
                [
                    f"【知识笔记】{title}",
                    "",
                    summary,
                    "",
                    "可关注的点：",
                    "1. 这条信息是否能改善当前知识管理流程。",
                    "2. 是否值得加入个人知识库或后续深读清单。",
                    "",
                    f"原文：{article.get('url', '')}",
                ]
            ).strip()
            return json.dumps({"post_text": post_text, "issues": []}, ensure_ascii=False)
        if task == "feedback":
            feedback = payload.get("feedback", [])
            positive = sum(1 for item in feedback if int(item.get("rating") or 0) >= 4)
            negative = sum(1 for item in feedback if int(item.get("rating") or 0) <= 2)
            text = " ".join(str(item.get("feedback_text", "")) for item in feedback).lower()
            if negative > positive or any(word in text for word in ["bad", "差", "不喜欢", "没用"]):
                sentiment = "negative"
            elif positive > negative or any(word in text for word in ["good", "喜欢", "有用", "不错"]):
                sentiment = "positive"
            else:
                sentiment = "neutral"
            extracted = []
            for item in feedback:
                value = str(item.get("feedback_text", "")).strip()
                if value:
                    extracted.append(value[:200])
                elif item.get("feedback_type"):
                    extracted.append(f"{item.get('feedback_type')} rating={item.get('rating', 0)}")
            return json.dumps({"sentiment": sentiment, "extracted_feedback": extracted, "issues": []}, ensure_ascii=False)
        return "{}"


class OpenAICompatibleLLMClient(LLMClient):
    provider_name = "openai"

    def __init__(self, settings: OpenAISettings, api_key: str) -> None:
        self.settings = settings
        self.api_key = api_key

    def complete_json(self, task: str, system_prompt: str, user_prompt: str) -> str:
        endpoint = self.settings.base_url.rstrip("/") + "/chat/completions"
        body = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        req = urlrequest.Request(
            endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except URLError as exc:
            raise RuntimeError(f"OpenAI compatible request failed: {exc}") from exc
        try:
            return str(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("OpenAI compatible response did not contain choices[0].message.content") from exc


class ClaudeLLMClient(LLMClient):
    provider_name = "claude"

    def __init__(self, settings: ClaudeSettings, api_key: str) -> None:
        self.settings = settings
        self.api_key = api_key

    def complete_json(self, task: str, system_prompt: str, user_prompt: str) -> str:
        raise RuntimeError("Claude provider interface is reserved but not implemented in this MVP")


class LLMTool:
    def __init__(self, client: LLMClient, fallback_client: LLMClient | None = None, startup_warnings: list[str] | None = None) -> None:
        self.client = client
        self.fallback_client = fallback_client or MockLLMClient()
        self.startup_warnings = startup_warnings or []

    @property
    def provider_name(self) -> str:
        return self.client.provider_name

    def summarize(self, article: JsonDict, user_profile_snapshot: JsonDict, skill_text: str) -> SummaryLLMOutput:
        payload = {"article": article, "user_profile_snapshot": user_profile_snapshot}
        return self._generate_structured(
            task="summary",
            schema=SummaryLLMOutput,
            system_prompt=(
                "You summarize articles into concise Chinese knowledge notes. "
                "Return strict JSON with fields: summary string, issues string array.\n\n"
                f"Skill:\n{skill_text}"
            ),
            payload=payload,
            fallback=lambda issue: SummaryLLMOutput(summary=self._fallback_summary(article), issues=[issue]),
        )

    def rewrite_post(self, article: JsonDict, summary: str, skill_text: str) -> RewriteLLMOutput:
        payload = {"article": article, "summary": summary}
        return self._generate_structured(
            task="rewrite",
            schema=RewriteLLMOutput,
            system_prompt=(
                "Rewrite the summary into a useful Chinese knowledge post. Avoid clickbait and marketing tone. "
                "Return strict JSON with fields: post_text string, issues string array.\n\n"
                f"Skill:\n{skill_text}"
            ),
            payload=payload,
            fallback=lambda issue: RewriteLLMOutput(post_text=self._fallback_post(article, summary), issues=[issue]),
        )

    def extract_feedback(self, feedback: list[JsonDict], skill_text: str) -> FeedbackLLMOutput:
        payload = {"feedback": feedback}
        return self._generate_structured(
            task="feedback",
            schema=FeedbackLLMOutput,
            system_prompt=(
                "Extract preference signals from user feedback. "
                "Return strict JSON with fields: sentiment positive|neutral|negative, extracted_feedback string array, issues string array.\n\n"
                f"Skill:\n{skill_text}"
            ),
            payload=payload,
            fallback=lambda issue: self._fallback_feedback(feedback, issue),
        )

    def _generate_structured(
        self,
        task: str,
        schema: type[SchemaT],
        system_prompt: str,
        payload: JsonDict,
        fallback: Any,
    ) -> SchemaT:
        user_prompt = json.dumps(payload, ensure_ascii=False)
        try:
            raw = self.client.complete_json(task, system_prompt, user_prompt)
            return _validate_schema(schema, _parse_json(raw))
        except Exception as first_error:
            LOGGER.warning("LLM %s output failed validation for %s: %s", self.client.provider_name, task, first_error)
            try:
                repair_prompt = (
                    "Fix the previous response into valid JSON for the requested schema. "
                    "Return JSON only.\n\n"
                    f"Schema fields: {list(schema.model_fields.keys())}\n"
                    f"Original payload: {user_prompt}\n"
                    f"Previous error: {first_error}"
                )
                raw = self.client.complete_json(task, system_prompt, repair_prompt)
                return _validate_schema(schema, _parse_json(raw))
            except Exception as repair_error:
                LOGGER.warning("LLM %s repair failed for %s: %s", self.client.provider_name, task, repair_error)
                issue = f"llm_fallback:{self.client.provider_name}:{type(repair_error).__name__}"
                return fallback(issue)

    def _fallback_summary(self, article: JsonDict) -> str:
        return _validate_schema(
            SummaryLLMOutput,
            _parse_json(self.fallback_client.complete_json("summary", "", json.dumps({"article": article}, ensure_ascii=False))),
        ).summary

    def _fallback_post(self, article: JsonDict, summary: str) -> str:
        return _validate_schema(
            RewriteLLMOutput,
            _parse_json(
                self.fallback_client.complete_json(
                    "rewrite",
                    "",
                    json.dumps({"article": article, "summary": summary}, ensure_ascii=False),
                )
            ),
        ).post_text

    def _fallback_feedback(self, feedback: list[JsonDict], issue: str) -> FeedbackLLMOutput:
        output = _validate_schema(
            FeedbackLLMOutput,
            _parse_json(self.fallback_client.complete_json("feedback", "", json.dumps({"feedback": feedback}, ensure_ascii=False))),
        )
        output.issues.append(issue)
        return output


def build_llm_tool(settings: Settings) -> LLMTool:
    client, warnings = build_llm_client(settings.llm)
    return LLMTool(client=client, startup_warnings=warnings)


def build_llm_client(settings: LLMSettings) -> tuple[LLMClient, list[str]]:
    provider = settings.provider.strip().lower()
    warnings: list[str] = []
    if provider == "mock":
        return MockLLMClient(), warnings
    if provider in {"openai", "openai-compatible", "openai_compatible"}:
        api_key = os.getenv(settings.openai.api_key_env, "")
        if not api_key:
            message = f"Missing `{settings.openai.api_key_env}`; falling back to mock LLM provider"
            LOGGER.warning(message)
            warnings.append(message)
            return MockLLMClient(), warnings
        return OpenAICompatibleLLMClient(settings.openai, api_key), warnings
    if provider == "claude":
        api_key = os.getenv(settings.claude.api_key_env, "")
        if not api_key:
            message = f"Missing `{settings.claude.api_key_env}`; falling back to mock LLM provider"
            LOGGER.warning(message)
            warnings.append(message)
            return MockLLMClient(), warnings
        message = "Claude provider is a stub in this MVP; calls fall back per request if used"
        LOGGER.warning(message)
        warnings.append(message)
        return ClaudeLLMClient(settings.claude, api_key), warnings
    message = f"Unknown LLM provider `{provider}`; falling back to mock LLM provider"
    LOGGER.warning(message)
    warnings.append(message)
    return MockLLMClient(), warnings


def _parse_json(raw: str) -> JsonDict:
    text = raw.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("LLM JSON output must be an object")
    return value


def _validate_schema(schema: type[SchemaT], value: JsonDict) -> SchemaT:
    try:
        return schema.model_validate(value)
    except ValidationError:
        raise


def _load_prompt_payload(user_prompt: str) -> JsonDict:
    try:
        value = json.loads(user_prompt)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}
