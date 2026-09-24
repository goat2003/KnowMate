"""LLM-first query analysis and retrieval route planning."""

from __future__ import annotations

import inspect
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from app.retrieval.utils import clean_text_list

logger = logging.getLogger(__name__)

ALLOWED_ROUTES = ("fact", "relation", "vector")
DEFAULT_ROUTES = ["fact", "relation", "vector"]
ALLOWED_INTENTS = {
    "fact_lookup",
    "relation_lookup",
    "path_reasoning",
    "vector_recall",
    "temporal_lookup",
    "mixed",
}
ALLOWED_RELATION_INTENTS = {"entity_relation", "path", "causal", ""}

_RELATION_HINT_WORDS = (
    "关系",
    "联系",
    "关联",
    "路径",
    "间接关系",
    "为什么",
    "原因",
    "因果",
    "影响",
    "如何影响",
    "通过",
    "连接",
    "共同点",
)
_TIME_HINT_WORDS = (
    "今天",
    "昨天",
    "前天",
    "明天",
    "最近",
    "近期",
    "刚才",
    "上周",
    "本周",
    "这周",
    "上个月",
    "本月",
    "今年",
    "去年",
)
_TECH_HINT_WORDS = (
    "RAG",
    "LLM",
    "API",
    "JSON",
    "SQL",
    "NoSQL",
    "HTTP",
    "HTTPS",
    "GPU",
    "CPU",
)
_ENTITY_RELATION_QUERY_WORDS = (
    "关系",
    "联系",
    "关联",
    "影响",
    "为什么",
    "路径",
    "因果",
    "连接",
    "通过",
    "和",
    "跟",
    "与",
)


class QueryAnalysisError(ValueError):
    """Raised when LLM analysis cannot be converted into a retrieval plan."""


@dataclass
class LLMAnalysisResult:
    payload: Dict[str, Any]
    raw_output: str


@dataclass
class QueryPreprocessResult:
    query_text: str
    original_query: str
    current_time_iso: str


class MinimalRuleFallbackAnalyzer:
    """Stable low-quality fallback used only when LLM analysis fails."""

    def analyze(
        self,
        query_text: str,
        current_time: Optional[datetime | str] = None,
    ) -> Dict[str, Any]:
        query = str(query_text or "").strip()
        return {
            "sub_queries": [
                {
                    "query": query,
                    "routes": list(DEFAULT_ROUTES),
                    "entities": [],
                    "keywords": clean_text_list([query])[:1],
                    "relation_intent": "",
                    "relation_keywords": [],
                    "max_hops": 1,
                    "time": {
                        "has_time_constraint": False,
                        "start": "",
                        "end": "",
                        "raw": "",
                    },
                }
            ]
        }


class LLMQueryAnalyzer:
    """Calls the LLM to produce a structured retrieval plan."""

    def __init__(
        self,
        client_getter: Optional[Callable[[], Any]] = None,
        max_retries: int = 1,
    ):
        self.client_getter = client_getter
        self.max_retries = max_retries

    async def analyze(
        self,
        role_id: str,
        query_text: str,
        current_time: str,
        local_hints: Dict[str, Any],
        user_profile: str = "",
        target_object: str = "",
    ) -> LLMAnalysisResult:
        client = await self._get_client()
        prompt = self._build_prompt(
            role_id=role_id,
            query_text=query_text,
            current_time=current_time,
            local_hints=local_hints,
            user_profile=user_profile,
            target_object=target_object,
        )
        try:
            response = await client.chat(
                prompt=prompt,
                json_mode=True,
                temperature=0.0,
                max_retries=self.max_retries,
            )
        except Exception as exc:
            raise QueryAnalysisError(f"LLM request failed: {exc}") from exc

        content = getattr(response, "content", response)
        raw_output = self._raw_output(content)
        payload = self._coerce_payload(content)
        return LLMAnalysisResult(payload=payload, raw_output=raw_output)

    async def _get_client(self) -> Any:
        try:
            if self.client_getter is None:
                from app.common.client.llm_client import get_llm_client

                client_or_awaitable = get_llm_client()
            else:
                client_or_awaitable = self.client_getter()
            if inspect.isawaitable(client_or_awaitable):
                return await client_or_awaitable
            return client_or_awaitable
        except Exception as exc:
            raise QueryAnalysisError(f"LLM client unavailable: {exc}") from exc

    @staticmethod
    def _raw_output(content: Any) -> str:
        if isinstance(content, (dict, list)):
            return json.dumps(content, ensure_ascii=False)
        return str(content or "")

    @staticmethod
    def _coerce_payload(content: Any) -> Dict[str, Any]:
        if isinstance(content, dict):
            if not content:
                raise QueryAnalysisError("LLM returned empty JSON")
            return content
        if isinstance(content, str):
            raw = content.strip()
            if not raw:
                raise QueryAnalysisError("LLM returned empty output")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise QueryAnalysisError("LLM returned non-JSON output") from exc
            if not isinstance(parsed, dict) or not parsed:
                raise QueryAnalysisError("LLM JSON root must be a non-empty object")
            return parsed
        raise QueryAnalysisError(f"LLM returned unsupported content type: {type(content).__name__}")

    @staticmethod
    def _build_prompt(
        role_id: str,
        query_text: str,
        current_time: str,
        local_hints: Dict[str, Any],
        user_profile: str = "",
        target_object: str = "",
    ) -> str:
        hints_json = json.dumps(local_hints, ensure_ascii=False, indent=2)
        profile_text = LLMQueryAnalyzer._truncate_profile(user_profile)
        target_object_text = str(target_object or "").strip()
        profile_block = ""
        if profile_text.strip():
            profile_block = f"""

用户画像上下文：
{profile_text}

用户画像使用规则：
1. 用户画像只用于辅助理解用户问题、解析代词和模糊表达、补充实体候选、选择检索路由和拆分子问题。
2. 不要把用户画像当作最终事实证据直接回答用户。
3. 不要编造画像中没有的信息。
4. 如果用户问题询问“我是谁、我的基本信息、我的偏好、我的经历”等，可以优先包含 fact route，同时保留 vector route。
5. 如果用户问题中的代词或模糊表达能被用户画像帮助消解，可以在 keywords/entities 中体现消解后的关键词。
6. 仍然必须输出 JSON 检索计划，不要回答用户问题。
"""
        return f"""你是记忆检索系统的查询分析器。你的任务不是回答用户问题，而是把用户问题转换成检索计划。

语言归一化规则：
无论用户问题 query 使用何种语言，你都必须先将 query 理解并转换为英文语义，再基于英文语义完成实体抽取、关键词抽取、意图判断、子问题拆分、检索路由选择、时间解析和关系意图判断。
输出 JSON 中所有可自由生成的文本字段也必须使用英文，包括 entities、keywords、sub_queries.query、sub_queries.entities、sub_queries.keywords、sub_queries.relation_keywords 和 time.raw。
人名、地名、品牌名、ID、代码名等专有名词可以保留原始写法。

role_id：{role_id}
当前时间：{current_time}
target_object：{target_object_text}
用户问题：{query_text}
本地提示：
{hints_json}
{profile_block}

可用检索路由：
- fact：用于检索用户明确事实、偏好、经历、身份、稳定记忆。
- relation：用于检索实体之间的关系、因果、路径、多跳联系。
- vector：用于检索原始对话片段、模糊语义、总结型或开放型问题。

你必须完成：
1. 抽取实体 entities。
2. 抽取关键词 keywords。
3. 判断总意图 intent。
4. 拆分子问题 sub_queries。
5. 为每个子问题选择 routes。
6. 解析时间约束 time。
7. 判断关系意图 relation_intent 和 max_hops。

要求：
1. 只输出 JSON，不要输出解释文字。
2. 不要编造用户事实。
3. 实体必须来自用户问题本身或其明确指代，不要凭空扩展。
4. 子问题必须保持用户原意。
5. 最多拆成 4 个子问题。
6. routes 只能使用 fact、relation、vector。
7. 如果问题包含今天、昨天、最近、上周、某日期，必须解析 time。
8. 如果问题询问 X 和 Y 的关系，relation_intent 使用 entity_relation。
9. 如果问题询问“通过什么联系起来、路径、间接关系”，relation_intent 使用 path，max_hops 设为 2 或 3。
10. 如果问题是模糊回忆、总结、开放问题，必须包含 vector route。
11. 如果问题是用户偏好、经历、身份、明确事实，必须包含 fact route。
12. LLM 只负责检索前结构化分析，不要回答用户问题，不要访问数据库。
13. If query uses first-person pronouns such as "I", "me", "my", or "mine" as the subject or owner, replace them with the concrete value shown in the target_object field. Never output the literal string "target_object". Use target_object only to disambiguate pronouns for retrieval planning; do not invent facts about target_object.

输出 JSON schema：
{{
  "intent": "fact_lookup|relation_lookup|path_reasoning|vector_recall|temporal_lookup|mixed",
  "entities": ["全局实体1", "全局实体2"],
  "keywords": ["全局关键词1", "全局关键词2"],
  "sub_queries": [
    {{
      "query": "可独立检索的子问题",
      "routes": ["fact", "relation", "vector"],
      "entities": ["实体1", "实体2"],
      "keywords": ["关键词1", "关键词2"],
      "relation_intent": "entity_relation|path|causal|",
      "relation_keywords": ["关系词"],
      "max_hops": 1,
      "time": {{
        "has_time_constraint": false,
        "start": "",
        "end": "",
        "raw": ""
      }}
    }}
  ]
}}"""

    @staticmethod
    def _truncate_profile(user_profile: str, limit: int = 2000) -> str:
        text = str(user_profile or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "\n[truncated]"


class QueryAnalyzer:
    """Public analyzer entry point used by RetrievalService."""

    def __init__(
        self,
        use_llm: bool = True,
        *,
        force_fallback: bool = False,
        llm_analyzer: Optional[LLMQueryAnalyzer] = None,
        fallback_analyzer: Optional[MinimalRuleFallbackAnalyzer] = None,
        llm_client_getter: Optional[Callable[[], Any]] = None,
    ):
        # Kept for old constructors. It no longer disables the LLM-first path.
        self.use_llm = use_llm
        self.force_fallback = force_fallback
        self.llm_analyzer = llm_analyzer or LLMQueryAnalyzer(client_getter=llm_client_getter)
        self.fallback_analyzer = fallback_analyzer or MinimalRuleFallbackAnalyzer()

    async def analyze(
        self,
        role_id: str,
        query_text: str,
        current_time: Optional[datetime | str] = None,
        user_profile: str = "",
        target_object: str = "",
    ) -> Dict[str, Any]:
        prepared = self._preprocess(query_text=query_text, current_time=current_time)
        if self.force_fallback:
            return self._fallback_result(
                prepared,
                "force_fallback enabled",
                user_profile=user_profile,
                target_object=target_object,
            )

        local_hints = self._extract_local_hints(prepared.query_text)
        try:
            llm_result = await self.llm_analyzer.analyze(
                role_id=role_id,
                query_text=prepared.query_text,
                current_time=prepared.current_time_iso,
                local_hints=local_hints,
                user_profile=user_profile,
                target_object=target_object,
            )
            normalized, warnings = self._normalize_payload(
                payload=llm_result.payload,
                query_text=prepared.query_text,
                target_object=target_object,
            )
            normalized["analysis_debug"] = self._llm_debug(
                payload=llm_result.payload,
                raw_llm_output=llm_result.raw_output,
                warnings=warnings,
                user_profile=user_profile,
                target_object=target_object,
            )
            return normalized
        except Exception as exc:
            reason = str(exc) or exc.__class__.__name__
            logger.warning("LLM query analysis failed, using fallback: %s", reason)
            return self._fallback_result(
                prepared,
                reason,
                user_profile=user_profile,
                target_object=target_object,
            )

    def _fallback_result(
        self,
        prepared: QueryPreprocessResult,
        reason: str,
        user_profile: str = "",
        target_object: str = "",
    ) -> Dict[str, Any]:
        result = self.fallback_analyzer.analyze(
            query_text=prepared.query_text,
            current_time=prepared.current_time_iso,
        )
        self._resolve_target_object_in_result(result, target_object)
        profile_text = str(user_profile or "")
        target_object_text = str(target_object or "")
        result["analysis_debug"] = {
            "analyzer": "fallback",
            "fallback_used": True,
            "fallback_reason": reason,
            "intent": "",
            "top_level_entities": [],
            "top_level_keywords": [],
            "raw_llm_output": "",
            "normalization_warnings": [],
            "profile_included": bool(profile_text.strip()),
            "profile_chars": len(profile_text),
            "target_object_included": bool(target_object_text.strip()),
            "target_object": target_object_text,
        }
        return result

    @classmethod
    def _resolve_target_object_in_result(cls, result: Dict[str, Any], target_object: str) -> None:
        replacement = str(target_object or "").strip()
        if not replacement or not isinstance(result, dict):
            return
        for sub_query in result.get("sub_queries") or []:
            if not isinstance(sub_query, dict):
                continue
            sub_query["query"] = cls._resolve_target_object_text(sub_query.get("query") or "", replacement)
            sub_query["entities"] = cls._resolve_target_object_list(sub_query.get("entities") or [], replacement)
            sub_query["keywords"] = cls._resolve_target_object_list(sub_query.get("keywords") or [], replacement)
            sub_query["relation_keywords"] = cls._resolve_target_object_list(
                sub_query.get("relation_keywords") or [],
                replacement,
            )

    @staticmethod
    def _llm_debug(
        payload: Dict[str, Any],
        raw_llm_output: str,
        warnings: List[str],
        user_profile: str = "",
        target_object: str = "",
    ) -> Dict[str, Any]:
        intent = str(payload.get("intent") or "").strip()
        if intent not in ALLOWED_INTENTS:
            intent = intent or "mixed"
        profile_text = str(user_profile or "")
        target_object_text = str(target_object or "")
        return {
            "analyzer": "llm",
            "fallback_used": False,
            "fallback_reason": "",
            "intent": intent,
            "top_level_entities": QueryAnalyzer._clean_str_list(payload.get("entities"), limit=12),
            "top_level_keywords": QueryAnalyzer._clean_str_list(payload.get("keywords"), limit=16),
            "raw_llm_output": raw_llm_output,
            "normalization_warnings": warnings,
            "profile_included": bool(profile_text.strip()),
            "profile_chars": len(profile_text),
            "target_object_included": bool(target_object_text.strip()),
            "target_object": target_object_text,
        }

    @staticmethod
    def _preprocess(
        query_text: str,
        current_time: Optional[datetime | str],
    ) -> QueryPreprocessResult:
        original_query = str(query_text or "")
        cleaned_query = re.sub(r"\s+", " ", original_query).strip()
        if isinstance(current_time, datetime):
            current_time_iso = current_time.isoformat()
        elif current_time:
            value = str(current_time).strip()
            try:
                current_time_iso = datetime.fromisoformat(value).isoformat()
            except ValueError:
                current_time_iso = value
        else:
            current_time_iso = datetime.now().isoformat()
        return QueryPreprocessResult(
            query_text=cleaned_query,
            original_query=original_query,
            current_time_iso=current_time_iso,
        )

    @staticmethod
    def _extract_local_hints(query_text: str) -> Dict[str, Any]:
        text = str(query_text or "")
        quoted_terms = re.findall(r"[\"'“”‘’《》](.*?)[\"'“”‘’《》]", text)
        english_terms = re.findall(r"\b[A-Za-z][A-Za-z0-9_+#./-]*\b", text)
        uppercase_terms = [term for term in english_terms if term.isupper() and len(term) > 1]
        date_terms = re.findall(r"\b20\d{2}[-/.年]\d{1,2}(?:[-/.月]\d{1,2}日?)?\b", text)
        time_words = [word for word in _TIME_HINT_WORDS if word in text]
        relation_words = [word for word in _RELATION_HINT_WORDS if word in text]
        tech_terms = [word for word in _TECH_HINT_WORDS if word in text]
        special_terms = clean_text_list([*quoted_terms, *english_terms, *uppercase_terms, *tech_terms])
        return {
            "possible_time_words": clean_text_list([*time_words, *date_terms])[:12],
            "possible_relation_words": clean_text_list(relation_words)[:12],
            "possible_special_terms": special_terms[:16],
        }

    def _normalize_payload(
        self,
        payload: Dict[str, Any],
        query_text: str,
        target_object: str = "",
    ) -> tuple[Dict[str, Any], List[str]]:
        if not isinstance(payload, dict):
            raise QueryAnalysisError("LLM payload is not an object")

        warnings: List[str] = []
        top_entities = self._clean_str_list(payload.get("entities"), limit=12)
        top_keywords = self._clean_str_list(payload.get("keywords"), limit=16)
        raw_sub_queries = payload.get("sub_queries")
        if not isinstance(raw_sub_queries, list) or not raw_sub_queries:
            raise QueryAnalysisError("LLM payload has no sub_queries")

        sub_queries: List[Dict[str, Any]] = []
        for index, item in enumerate(raw_sub_queries[:4]):
            if not isinstance(item, dict):
                warnings.append(f"sub_queries[{index}] is not an object and was skipped")
                continue
            sub_query = self._normalize_sub_query(
                item=item,
                index=index,
                query_text=query_text,
                top_entities=top_entities,
                top_keywords=top_keywords,
                target_object=target_object,
                warnings=warnings,
            )
            sub_queries.append(sub_query)

        if not sub_queries:
            raise QueryAnalysisError("LLM sub_queries could not be normalized")
        return {"sub_queries": sub_queries}, warnings

    def _normalize_sub_query(
        self,
        item: Dict[str, Any],
        index: int,
        query_text: str,
        top_entities: List[str],
        top_keywords: List[str],
        target_object: str,
        warnings: List[str],
    ) -> Dict[str, Any]:
        query = str(item.get("query") or query_text or "").strip()
        if not query:
            raise QueryAnalysisError(f"sub_queries[{index}].query is empty")

        entities = self._clean_str_list(item.get("entities"), limit=12) or top_entities
        keywords = self._clean_str_list(item.get("keywords"), limit=16) or top_keywords
        relation_keywords = self._clean_str_list(item.get("relation_keywords"), limit=12)
        query = self._resolve_target_object_text(query, target_object)
        entities = self._resolve_target_object_list(entities, target_object)
        keywords = self._resolve_target_object_list(keywords, target_object)
        relation_keywords = self._resolve_target_object_list(relation_keywords, target_object)
        relation_intent = self._normalize_relation_intent(
            item.get("relation_intent"),
            index=index,
            warnings=warnings,
        )
        max_hops = self._normalize_max_hops(item.get("max_hops"), index=index, warnings=warnings)
        time_info = self._normalize_time(item.get("time"), index=index, warnings=warnings)

        relation_like = self._looks_like_relation_query(
            query=query,
            entities=entities,
            relation_intent=relation_intent,
            relation_keywords=relation_keywords,
        )
        if relation_like and len(entities) >= 2 and max_hops < 2:
            max_hops = 2
            warnings.append(f"sub_queries[{index}].max_hops raised to 2 for relation query")
        if relation_intent == "path" and max_hops < 2:
            max_hops = 2
            warnings.append(f"sub_queries[{index}].max_hops raised to 2 for path intent")

        routes = self._normalize_routes(
            value=item.get("routes"),
            index=index,
            relation_intent=relation_intent,
            relation_like=relation_like,
            has_time_constraint=bool(time_info.get("has_time_constraint")),
            warnings=warnings,
        )

        return {
            "query": query,
            "routes": routes,
            "entities": entities,
            "keywords": keywords,
            "relation_intent": relation_intent,
            "relation_keywords": relation_keywords,
            "max_hops": max_hops,
            "time": time_info,
        }

    @staticmethod
    def _resolve_target_object_text(text: str, target_object: str) -> str:
        replacement = str(target_object or "").strip()
        value = str(text or "")
        if not replacement:
            return value.strip()
        value = re.sub(r"\btarget_object\b", replacement, value, flags=re.IGNORECASE)
        value = re.sub(r"\b(I|me|my|mine)\b", replacement, value, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", value).strip()

    @classmethod
    def _resolve_target_object_list(cls, values: List[str], target_object: str) -> List[str]:
        resolved = [cls._resolve_target_object_text(value, target_object) for value in values]
        return clean_text_list(resolved)

    @staticmethod
    def _normalize_relation_intent(value: Any, index: int, warnings: List[str]) -> str:
        relation_intent = str(value or "").strip()
        if relation_intent not in ALLOWED_RELATION_INTENTS:
            warnings.append(f"sub_queries[{index}].relation_intent was invalid and cleared")
            return ""
        return relation_intent

    @staticmethod
    def _clean_str_list(value: Any, limit: int) -> List[str]:
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, (list, tuple, set)):
            values = list(value)
        else:
            values = []
        return clean_text_list(values)[:limit]

    @staticmethod
    def _normalize_max_hops(value: Any, index: int, warnings: List[str]) -> int:
        try:
            max_hops = int(value)
        except (TypeError, ValueError):
            if value not in (None, ""):
                warnings.append(f"sub_queries[{index}].max_hops was invalid and set to 1")
            max_hops = 1
        clamped = max(1, min(max_hops, 3))
        if clamped != max_hops:
            warnings.append(f"sub_queries[{index}].max_hops clamped to {clamped}")
        return clamped

    @staticmethod
    def _normalize_time(value: Any, index: int, warnings: List[str]) -> Dict[str, Any]:
        if not isinstance(value, dict):
            if value not in (None, ""):
                warnings.append(f"sub_queries[{index}].time was invalid and reset")
            value = {}

        raw = str(value.get("raw") or "").strip()
        start = QueryAnalyzer._stringify_time(value.get("start"))
        end = QueryAnalyzer._stringify_time(value.get("end"))
        has_time_constraint = bool(value.get("has_time_constraint") or raw or start or end)
        return {
            "has_time_constraint": has_time_constraint,
            "start": start,
            "end": end,
            "raw": raw,
        }

    @staticmethod
    def _stringify_time(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.isoformat()
        text = str(value).strip()
        if not text:
            return ""
        try:
            return datetime.fromisoformat(text).isoformat()
        except ValueError:
            return text

    @staticmethod
    def _normalize_routes(
        value: Any,
        index: int,
        relation_intent: str,
        relation_like: bool,
        has_time_constraint: bool,
        warnings: List[str],
    ) -> List[str]:
        raw_routes: List[Any]
        if isinstance(value, str):
            raw_routes = [part for part in re.split(r"[\s,，/|]+", value) if part]
        elif isinstance(value, list):
            raw_routes = value
        else:
            raw_routes = []

        routes: List[str] = []
        invalid_routes: List[str] = []
        for route in raw_routes:
            route_text = str(route or "").strip().lower()
            if not route_text:
                continue
            if route_text in ALLOWED_ROUTES:
                routes.append(route_text)
            else:
                invalid_routes.append(route_text)
        if invalid_routes:
            warnings.append(f"sub_queries[{index}].routes dropped invalid values: {invalid_routes}")

        routes = QueryAnalyzer._unique_routes(routes)
        if not routes:
            routes = list(DEFAULT_ROUTES)
            warnings.append(f"sub_queries[{index}].routes defaulted to all routes")

        if relation_intent and "relation" not in routes:
            routes = ["relation", *routes]
            warnings.append(f"sub_queries[{index}].routes added relation for relation_intent")
        elif relation_like and "relation" not in routes:
            routes = ["relation", *routes]
            warnings.append(f"sub_queries[{index}].routes added relation for entity relation query")

        if has_time_constraint and routes == ["relation"]:
            routes.append("fact")
            warnings.append(f"sub_queries[{index}].routes added fact for temporal relation query")

        return QueryAnalyzer._unique_routes(routes)[:3]

    @staticmethod
    def _unique_routes(routes: List[str]) -> List[str]:
        result: List[str] = []
        for route in routes:
            if route in ALLOWED_ROUTES and route not in result:
                result.append(route)
        return result

    @staticmethod
    def _looks_like_relation_query(
        query: str,
        entities: List[str],
        relation_intent: str,
        relation_keywords: List[str],
    ) -> bool:
        text = str(query or "")
        if relation_intent or relation_keywords:
            return True
        if len(entities or []) < 2:
            return False
        return any(word in text for word in _ENTITY_RELATION_QUERY_WORDS)
