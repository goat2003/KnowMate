# 文件作用：
# 本文件封装 Python Agent Service 中所有 LLM 调用逻辑。
# 它负责选择 mock / OpenAI-compatible / Claude provider，向模型发送提示词，
# 并使用 Pydantic 校验模型返回的结构化 JSON。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的工具层，被 SummaryAgent、RewriteAgent、FeedbackAgent 共同调用。
#
# 主要内容：
# 1. SummaryLLMOutput / RewriteLLMOutput / FeedbackLLMOutput：定义 LLM 结构化输出 schema。
# 2. LLMClient：定义不同 LLM provider 的统一接口。
# 3. MockLLMClient：本地 mock provider，不访问外部 API，便于测试和离线开发。
# 4. OpenAICompatibleLLMClient：通过 /chat/completions 调用 OpenAI 兼容接口。
# 5. ClaudeLLMClient：保留 Claude provider 接口，当前 MVP 未实现真实调用。
# 6. LLMTool：Agent 使用的统一入口，负责结构化生成、校验、repair 和 fallback。
# 7. build_llm_tool / build_llm_client：根据配置和环境变量创建 LLMTool。
#
# 关键调用关系：
# - 被 SummaryAgent.summarize、RewriteAgent.rewrite_post、FeedbackAgent.extract_feedback 调用。
# - 读取 Settings.llm 和环境变量中的 API Key。
# - 返回的 issues 会继续进入 article_results 或 feedback_issues，便于 GoFrame 记录问题。
#
# 初学者阅读建议：
# 先看 LLMTool 的三个公开方法，再看 _generate_structured 如何处理“调用 -> 解析 -> 校验 -> 修复 -> 兜底”。
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


# LOGGER 是本模块的日志对象，用于记录 LLM 输出校验失败、repair 失败、provider 配置缺失等问题。
LOGGER = logging.getLogger(__name__)
# SchemaT 是一个泛型类型变量，限制为 Pydantic BaseModel 的子类。
# 这样 _generate_structured 可以返回与传入 schema 对应的具体模型类型。
SchemaT = TypeVar("SchemaT", bound=BaseModel)


# 类作用：
# SummaryLLMOutput 定义摘要任务期望 LLM 返回的 JSON 结构。
# Pydantic 会校验 summary 至少有 1 个字符，issues 默认为空列表。
class SummaryLLMOutput(BaseModel):
    # summary 是最终给 GoFrame 和 Markdown 使用的文章摘要。
    summary: str = Field(min_length=1)
    # issues 记录 LLM 输出或业务处理中的问题，例如 fallback 标记。
    issues: list[str] = Field(default_factory=list)


# 类作用：
# RewriteLLMOutput 定义改写任务期望 LLM 返回的 JSON 结构。
# post_text 是最终推文/知识笔记文本，issues 用于保留异常信息。
class RewriteLLMOutput(BaseModel):
    # post_text 是 RewriteAgent 写入 result["post_text"] 的正文。
    post_text: str = Field(min_length=1)
    # default_factory=list 表示每个模型实例都有自己的空列表，避免多个实例共享同一个 list。
    issues: list[str] = Field(default_factory=list)


# 类作用：
# FeedbackLLMOutput 定义反馈提取任务期望 LLM 返回的 JSON 结构。
# sentiment 只能是 positive、neutral、negative 三种值之一。
class FeedbackLLMOutput(BaseModel):
    # Literal 用于限制字符串取值范围，避免 LLM 返回任意情绪标签。
    sentiment: Literal["positive", "neutral", "negative"] = "neutral"
    # extracted_feedback 保存从反馈中提取出的用户偏好或问题信号。
    extracted_feedback: list[str] = Field(default_factory=list)
    # issues 记录解析、修复或 fallback 的问题。
    issues: list[str] = Field(default_factory=list)


# 类作用：
# LLMClient 是所有 LLM provider 的抽象基类。
# Agent 不直接关心 provider 细节，只依赖 complete_json 这个统一接口。
class LLMClient(ABC):
    # provider_name 用于日志、HealthCheck 和 fallback issue 标记。
    provider_name = "base"

    # 函数作用：
    # 定义一次“让 LLM 返回 JSON 字符串”的统一接口。
    #
    # 参数说明：
    # - task：任务名，例如 summary、rewrite、feedback。
    # - system_prompt：系统提示词，包含角色说明和技能规则。
    # - user_prompt：用户提示词，通常是 JSON 序列化后的业务 payload。
    #
    # 返回值：
    # - 返回模型输出的原始字符串，后续由 LLMTool 解析和校验。
    @abstractmethod
    def complete_json(self, task: str, system_prompt: str, user_prompt: str) -> str:
        # 抽象方法不提供实现，子类必须重写。
        raise NotImplementedError


# 类作用：
# MockLLMClient 是本地模拟 LLM provider。
# 它不读取 API Key、不访问网络，使用规则生成稳定 JSON，适合单元测试、离线开发和 demo。
class MockLLMClient(LLMClient):
    # provider_name 会显示为 mock，HealthCheck 可据此告诉 GoFrame 当前不是在调用真实 LLM。
    provider_name = "mock"

    # 函数作用：
    # 根据 task 返回符合 schema 的 mock JSON。
    #
    # 参数说明：
    # - task：summary、rewrite 或 feedback。
    # - system_prompt：mock 中暂不使用，但保留参数以匹配 LLMClient 接口。
    # - user_prompt：JSON 字符串，包含文章或反馈 payload。
    #
    # 返回值：
    # - 返回 JSON 字符串，供 LLMTool 按真实 provider 的路径继续解析和校验。
    def complete_json(self, task: str, system_prompt: str, user_prompt: str) -> str:
        # 从 user_prompt 中解析 payload；解析失败时会得到空字典，避免 mock 抛出异常。
        payload = _load_prompt_payload(user_prompt)
        # summary 任务模拟文章摘要。
        if task == "summary":
            # article 是 LLMTool.summarize 传入的文章对象。
            article = payload.get("article", {})
            # 标题缺失时使用默认标题，保证 summary schema 的 min_length 校验可通过。
            title = str(article.get("title") or "未命名文章")
            # raw_text 是文章正文；没有正文时使用空字符串。
            raw_text = str(article.get("raw_text") or "")
            # 将换行和多余空白压缩成单行，mock 摘要更稳定，测试更容易断言。
            compact = " ".join(raw_text.replace("\r", " ").replace("\n", " ").split())
            # 截取前 180 个字符作为摘要片段，避免 mock 输出过长。
            snippet = compact[:180] + ("..." if len(compact) > 180 else "")
            # 没有正文时生成占位摘要，明确这是由于原文内容不足导致。
            if not snippet:
                snippet = "原文内容较少，当前只能基于标题生成占位摘要。"
            # json.dumps(..., ensure_ascii=False) 保留中文字符，方便日志和响应阅读。
            return json.dumps({"summary": f"这篇文章《{title}》主要讨论：{snippet}", "issues": []}, ensure_ascii=False)
        # rewrite 任务模拟把摘要改写成知识笔记。
        if task == "rewrite":
            # 读取原文章，主要用于标题和原文 URL。
            article = payload.get("article", {})
            # 标题缺失时使用默认名称，避免输出为空。
            title = str(article.get("title") or "知识笔记")
            # summary 是 SummaryAgent 的输出，RewriteAgent 会把它传进来。
            summary = str(payload.get("summary") or "")
            # 用固定模板拼装 mock 推文，保证本地测试不依赖外部模型。
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
            # 返回 RewriteLLMOutput 需要的字段。
            return json.dumps({"post_text": post_text, "issues": []}, ensure_ascii=False)
        # feedback 任务模拟从反馈中提取情绪和偏好。
        if task == "feedback":
            # feedback 是用户反馈列表，每项可能包含 rating、feedback_text、feedback_type 等字段。
            feedback = payload.get("feedback", [])
            # 评分 >=4 视为正向信号。
            positive = sum(1 for item in feedback if int(item.get("rating") or 0) >= 4)
            # 评分 <=2 视为负向信号。
            negative = sum(1 for item in feedback if int(item.get("rating") or 0) <= 2)
            # 将反馈文本合并并小写化，用于关键词判断。
            text = " ".join(str(item.get("feedback_text", "")) for item in feedback).lower()
            # 负向评分更多或包含负向关键词时，情绪为 negative。
            if negative > positive or any(word in text for word in ["bad", "差", "不喜欢", "没用"]):
                sentiment = "negative"
            # 正向评分更多或包含正向关键词时，情绪为 positive。
            elif positive > negative or any(word in text for word in ["good", "喜欢", "有用", "不错"]):
                sentiment = "positive"
            # 没有明显倾向时保持 neutral。
            else:
                sentiment = "neutral"
            # extracted 保存从反馈中提取的可读偏好文本。
            extracted = []
            # 遍历每条反馈，优先保留用户写的文本。
            for item in feedback:
                value = str(item.get("feedback_text", "")).strip()
                # 有反馈文本时截断到 200 字，避免用户长文本让画像快照过大。
                if value:
                    extracted.append(value[:200])
                # 没有文本但有反馈类型时，用类型和评分生成一条简要信号。
                elif item.get("feedback_type"):
                    extracted.append(f"{item.get('feedback_type')} rating={item.get('rating', 0)}")
            # 返回 FeedbackLLMOutput 需要的字段。
            return json.dumps({"sentiment": sentiment, "extracted_feedback": extracted, "issues": []}, ensure_ascii=False)
        # 未知任务返回空 JSON；随后 Pydantic 校验通常会失败并触发 fallback。
        return "{}"


# 类作用：
# OpenAICompatibleLLMClient 通过 OpenAI 兼容的 chat completions HTTP API 调用真实模型。
# 只要服务实现 /chat/completions 且支持 response_format=json_object，就可以复用该客户端。
class OpenAICompatibleLLMClient(LLMClient):
    # provider_name 用于日志和 HealthCheck 展示。
    provider_name = "openai"

    # 函数作用：
    # 保存 OpenAI 兼容配置和 API Key。
    #
    # 参数说明：
    # - settings：包含 base_url、model、api_key_env 等配置。
    # - api_key：从环境变量读取到的真实 API Key。
    #
    # 返回值：
    # - 构造函数不返回值。
    def __init__(self, settings: OpenAISettings, api_key: str) -> None:
        # settings 决定请求地址和模型名称。
        self.settings = settings
        # api_key 只保存在内存中，用于 Authorization header。
        self.api_key = api_key

    # 函数作用：
    # 向 OpenAI 兼容接口发送一次 JSON 输出请求。
    #
    # 参数说明：
    # - task：任务名，仅用于接口统一；当前实现不直接使用。
    # - system_prompt：系统提示词。
    # - user_prompt：用户提示词，通常是 JSON payload。
    #
    # 返回值：
    # - 返回 choices[0].message.content 的字符串内容。
    #
    # 异常说明：
    # - 网络错误会包装成 RuntimeError。
    # - 响应结构不符合预期时也会抛 RuntimeError，交给 LLMTool 触发 repair 或 fallback。
    def complete_json(self, task: str, system_prompt: str, user_prompt: str) -> str:
        # rstrip("/") 防止 base_url 末尾有斜杠时拼出双斜杠路径。
        endpoint = self.settings.base_url.rstrip("/") + "/chat/completions"
        # 构造 OpenAI chat completions 请求体。
        body = {
            # model 来自配置或环境变量。
            "model": self.settings.model,
            # system/user 两段消息分别放规则和业务输入。
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            # 较低 temperature 用于提高结构化输出稳定性。
            "temperature": 0.2,
            # 要求模型返回 JSON object，降低解析失败概率。
            "response_format": {"type": "json_object"},
        }
        # urllib.request.Request 是标准库 HTTP 请求对象，避免额外引入第三方依赖。
        req = urlrequest.Request(
            endpoint,
            # 请求体按 UTF-8 编码，ensure_ascii=False 保留中文提示词。
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                # Authorization header 使用 Bearer token 传递 API Key。
                "Authorization": f"Bearer {self.api_key}",
                # 明确声明 JSON 和 UTF-8，避免服务端按错误编码解析中文。
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        # 捕获网络层错误；其他异常会继续抛出并由 LLMTool 的外层 try 处理。
        try:
            # with 会在响应读取结束后自动关闭连接资源。
            with urlrequest.urlopen(req, timeout=30) as response:
                # 读取响应字节并按 UTF-8 解析为 JSON 字典。
                payload = json.loads(response.read().decode("utf-8"))
        except URLError as exc:
            raise RuntimeError(f"OpenAI compatible request failed: {exc}") from exc
        # 从标准 chat completions 响应中取模型文本。
        try:
            return str(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            # 如果 provider 返回结构不符合 OpenAI 兼容协议，就显式报错，方便定位接口问题。
            raise RuntimeError("OpenAI compatible response did not contain choices[0].message.content") from exc


# 类作用：
# ClaudeLLMClient 预留 Claude provider 形状。
# 当前 MVP 没有实现真实 Claude HTTP 协议，因此如果被使用会抛错并触发 LLMTool fallback。
class ClaudeLLMClient(LLMClient):
    # provider_name 用于区分日志中的 Claude provider。
    provider_name = "claude"

    # 函数作用：
    # 保存 Claude 配置和 API Key。
    #
    # 参数说明：
    # - settings：Claude 模型和环境变量配置。
    # - api_key：从环境变量读取的 API Key。
    def __init__(self, settings: ClaudeSettings, api_key: str) -> None:
        # 保存配置，便于未来实现真实 Claude 调用。
        self.settings = settings
        # 保存 API Key，当前 MVP 不使用。
        self.api_key = api_key

    # 函数作用：
    # Claude provider 的统一接口占位实现。
    #
    # 参数说明：
    # - task/system_prompt/user_prompt：保持与 LLMClient 接口一致。
    #
    # 返回值：
    # - 当前不会正常返回，会抛出 RuntimeError。
    def complete_json(self, task: str, system_prompt: str, user_prompt: str) -> str:
        # 明确告诉调用方 Claude provider 尚未实现，而不是伪装成真实服务。
        raise RuntimeError("Claude provider interface is reserved but not implemented in this MVP")


# 类作用：
# LLMTool 是 Agent 调用 LLM 的统一门面。
# 它隐藏 provider 差异，并保证每次返回 Pydantic 校验过的结构化对象。
class LLMTool:
    # 函数作用：
    # 初始化 LLMTool。
    #
    # 参数说明：
    # - client：主 LLM provider 客户端。
    # - fallback_client：主 provider 失败后的兜底客户端，默认使用 MockLLMClient。
    # - startup_warnings：创建 provider 时产生的配置告警，例如 API Key 缺失。
    #
    # 返回值：
    # - 构造函数不返回值。
    def __init__(self, client: LLMClient, fallback_client: LLMClient | None = None, startup_warnings: list[str] | None = None) -> None:
        # client 是正常情况下使用的 provider。
        self.client = client
        # fallback_client 默认是 mock，确保真实 LLM 不可用时服务仍能返回可校验结构。
        self.fallback_client = fallback_client or MockLLMClient()
        # startup_warnings 记录初始化时的非致命问题，便于 HealthCheck 或日志观察。
        self.startup_warnings = startup_warnings or []

    # 属性作用：
    # 返回当前主 provider 名称，供 HealthCheck 判断是否处于 mock 模式。
    @property
    def provider_name(self) -> str:
        return self.client.provider_name

    # 函数作用：
    # 为 SummaryAgent 生成文章摘要。
    #
    # 参数说明：
    # - article：标准化后的文章字典。
    # - user_profile_snapshot：当前用户画像快照，可让摘要更贴近用户关注点。
    # - skill_text：摘要技能提示词。
    #
    # 返回值：
    # - 返回 SummaryLLMOutput，包含 summary 和 issues。
    def summarize(self, article: JsonDict, user_profile_snapshot: JsonDict, skill_text: str) -> SummaryLLMOutput:
        # payload 会作为 user prompt 发送给 LLM；保持 JSON 结构有助于模型输出稳定。
        payload = {"article": article, "user_profile_snapshot": user_profile_snapshot}
        # 调用统一结构化生成流程，指定 summary schema 和 fallback 方案。
        return self._generate_structured(
            task="summary",
            schema=SummaryLLMOutput,
            system_prompt=(
                "You summarize articles into concise Chinese knowledge notes. "
                "Return strict JSON with fields: summary string, issues string array.\n\n"
                f"Skill:\n{skill_text}"
            ),
            payload=payload,
            # 如果主 LLM 或 repair 都失败，就使用 mock fallback 生成摘要，并把 issue 写入结果。
            fallback=lambda issue: SummaryLLMOutput(summary=self._fallback_summary(article), issues=[issue]),
        )

    # 函数作用：
    # 为 RewriteAgent 把摘要改写为推文/知识笔记。
    #
    # 参数说明：
    # - article：原文章字典。
    # - summary：SummaryAgent 生成的摘要。
    # - skill_text：改写技能提示词。
    #
    # 返回值：
    # - 返回 RewriteLLMOutput，包含 post_text 和 issues。
    def rewrite_post(self, article: JsonDict, summary: str, skill_text: str) -> RewriteLLMOutput:
        # payload 同时包含原文章和摘要，让 LLM 能引用标题、URL 和摘要核心信息。
        payload = {"article": article, "summary": summary}
        # 通过统一流程调用 LLM，并要求结果符合 RewriteLLMOutput。
        return self._generate_structured(
            task="rewrite",
            schema=RewriteLLMOutput,
            system_prompt=(
                "Rewrite the summary into a useful Chinese knowledge post. Avoid clickbait and marketing tone. "
                "Return strict JSON with fields: post_text string, issues string array.\n\n"
                f"Skill:\n{skill_text}"
            ),
            payload=payload,
            # 兜底时用 mock provider 根据原文和摘要生成固定模板文本。
            fallback=lambda issue: RewriteLLMOutput(post_text=self._fallback_post(article, summary), issues=[issue]),
        )

    # 函数作用：
    # 为 FeedbackAgent 从用户反馈中提取情绪和偏好信号。
    #
    # 参数说明：
    # - feedback：反馈列表，每项包含 rating、feedback_text、feedback_type 等字段。
    # - skill_text：反馈提取技能提示词。
    #
    # 返回值：
    # - 返回 FeedbackLLMOutput，包含 sentiment、extracted_feedback 和 issues。
    def extract_feedback(self, feedback: list[JsonDict], skill_text: str) -> FeedbackLLMOutput:
        # 将反馈列表包装为 JSON 对象，便于 schema 和 prompt 统一处理。
        payload = {"feedback": feedback}
        # 使用统一结构化生成流程，失败时调用 _fallback_feedback。
        return self._generate_structured(
            task="feedback",
            schema=FeedbackLLMOutput,
            system_prompt=(
                "Extract preference signals from user feedback. "
                "Return strict JSON with fields: sentiment positive|neutral|negative, extracted_feedback string array, issues string array.\n\n"
                f"Skill:\n{skill_text}"
            ),
            payload=payload,
            # 反馈兜底仍返回合法 sentiment 和 extracted_feedback，并把失败原因加入 issues。
            fallback=lambda issue: self._fallback_feedback(feedback, issue),
        )

    # 函数作用：
    # 执行结构化 LLM 生成的完整流程：发送请求、解析 JSON、Pydantic 校验、repair、fallback。
    #
    # 参数说明：
    # - task：任务名称，传给 provider 和 mock provider。
    # - schema：期望输出的 Pydantic 模型类。
    # - system_prompt：系统提示词。
    # - payload：业务输入字典，会被 JSON 序列化为 user_prompt。
    # - fallback：repair 仍失败时调用的兜底函数。
    #
    # 返回值：
    # - 返回 schema 对应的 Pydantic 模型实例。
    #
    # 异常处理：
    # - 主调用、JSON 解析、Pydantic 校验任何一步失败都会进入 repair。
    # - repair 失败后不会继续抛给 gRPC 层，而是返回 fallback 结果，保证服务可用。
    def _generate_structured(
        self,
        task: str,
        schema: type[SchemaT],
        system_prompt: str,
        payload: JsonDict,
        fallback: Any,
    ) -> SchemaT:
        # 把业务 payload 序列化为 JSON 字符串；ensure_ascii=False 保留中文内容。
        user_prompt = json.dumps(payload, ensure_ascii=False)
        # 第一次尝试：直接让主 provider 生成 JSON，并按 schema 校验。
        try:
            raw = self.client.complete_json(task, system_prompt, user_prompt)
            return _validate_schema(schema, _parse_json(raw))
        except Exception as first_error:
            # 记录第一次失败原因，常见情况包括模型输出非 JSON、字段缺失、网络异常。
            LOGGER.warning("LLM %s output failed validation for %s: %s", self.client.provider_name, task, first_error)
            # 第二次尝试：让同一个 provider 修复上一次输出/错误，返回合法 JSON。
            try:
                # repair_prompt 告诉模型只返回 JSON，并列出目标 schema 字段和原始 payload。
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
                # repair 失败说明主 provider 当前不可用或输出不可控，此时进入本地 fallback。
                LOGGER.warning("LLM %s repair failed for %s: %s", self.client.provider_name, task, repair_error)
                # issue 字符串会进入 Agent 的 issues，方便在结果和日志中看到使用了兜底。
                issue = f"llm_fallback:{self.client.provider_name}:{type(repair_error).__name__}"
                return fallback(issue)

    # 函数作用：
    # 使用 fallback_client 生成摘要文本。
    #
    # 参数说明：
    # - article：原文章字典。
    #
    # 返回值：
    # - 返回 fallback 摘要字符串。
    def _fallback_summary(self, article: JsonDict) -> str:
        # fallback_client 也走 complete_json，再用同一个 schema 校验，保证兜底输出格式一致。
        return _validate_schema(
            SummaryLLMOutput,
            _parse_json(self.fallback_client.complete_json("summary", "", json.dumps({"article": article}, ensure_ascii=False))),
        ).summary

    # 函数作用：
    # 使用 fallback_client 生成推文/知识笔记文本。
    #
    # 参数说明：
    # - article：原文章字典。
    # - summary：摘要文本。
    #
    # 返回值：
    # - 返回 fallback post_text 字符串。
    def _fallback_post(self, article: JsonDict, summary: str) -> str:
        # 与正常 rewrite 一样传入 article 和 summary，保证 fallback 也能包含标题和 URL。
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

    # 函数作用：
    # 使用 fallback_client 提取反馈，并追加主 provider 失败原因。
    #
    # 参数说明：
    # - feedback：反馈列表。
    # - issue：主 provider/repair 失败时生成的问题标记。
    #
    # 返回值：
    # - 返回 FeedbackLLMOutput。
    def _fallback_feedback(self, feedback: list[JsonDict], issue: str) -> FeedbackLLMOutput:
        # fallback 输出仍需通过 FeedbackLLMOutput 校验。
        output = _validate_schema(
            FeedbackLLMOutput,
            _parse_json(self.fallback_client.complete_json("feedback", "", json.dumps({"feedback": feedback}, ensure_ascii=False))),
        )
        # 把失败原因追加到 issues，避免上游误以为真实 LLM 正常完成。
        output.issues.append(issue)
        return output


# 函数作用：
# 根据全局 Settings 创建 LLMTool。
#
# 参数说明：
# - settings：服务配置，包含 llm.provider、openai、claude 等配置。
#
# 返回值：
# - 返回可被 Agent 复用的 LLMTool。
#
# 调用关系：
# - 被 ArticleWorkflow.__init__ 调用。
def build_llm_tool(settings: Settings) -> LLMTool:
    # 先创建具体 provider client，再把初始化告警保存到 LLMTool。
    client, warnings = build_llm_client(settings.llm)
    return LLMTool(client=client, startup_warnings=warnings)


# 函数作用：
# 根据 LLMSettings 和环境变量选择具体 LLM provider。
#
# 参数说明：
# - settings：LLM 配置，包含 provider、OpenAI 配置、Claude 配置。
#
# 返回值：
# - 返回二元组：(LLMClient 实例, 初始化告警列表)。
#
# 选择规则：
# - provider=mock：直接使用 MockLLMClient。
# - provider=openai/openai-compatible/openai_compatible：读取 OPENAI_API_KEY 等环境变量，缺失则回退 mock。
# - provider=claude：读取 ANTHROPIC_API_KEY 等环境变量，但当前接口未实现，运行时会 fallback。
# - 未知 provider：回退 mock。
def build_llm_client(settings: LLMSettings) -> tuple[LLMClient, list[str]]:
    # strip().lower() 去除空格并统一小写，避免配置写成 OpenAI 或 " openai " 时无法匹配。
    provider = settings.provider.strip().lower()
    # warnings 收集非致命配置问题，供 LLMTool.startup_warnings 保存。
    warnings: list[str] = []
    # mock provider 不需要任何外部依赖，直接返回。
    if provider == "mock":
        return MockLLMClient(), warnings
    # OpenAI 兼容 provider 支持多种配置别名。
    if provider in {"openai", "openai-compatible", "openai_compatible"}:
        # API Key 环境变量名称也来自配置，便于兼容不同部署环境。
        api_key = os.getenv(settings.openai.api_key_env, "")
        # 没有 API Key 时不能调用真实服务，明确回退 mock，并记录警告。
        if not api_key:
            message = f"Missing `{settings.openai.api_key_env}`; falling back to mock LLM provider"
            LOGGER.warning(message)
            warnings.append(message)
            return MockLLMClient(), warnings
        # 有 API Key 时创建真实 OpenAI 兼容客户端。
        return OpenAICompatibleLLMClient(settings.openai, api_key), warnings
    # Claude provider 目前只保留接口形状。
    if provider == "claude":
        # Claude API Key 的环境变量名来自配置。
        api_key = os.getenv(settings.claude.api_key_env, "")
        # 缺少 API Key 时同样回退 mock。
        if not api_key:
            message = f"Missing `{settings.claude.api_key_env}`; falling back to mock LLM provider"
            LOGGER.warning(message)
            warnings.append(message)
            return MockLLMClient(), warnings
        # 即使有 API Key，当前 MVP 仍不实现 Claude 调用；返回 ClaudeLLMClient 后会在每次请求中触发 fallback。
        message = "Claude provider is a stub in this MVP; calls fall back per request if used"
        LOGGER.warning(message)
        warnings.append(message)
        return ClaudeLLMClient(settings.claude, api_key), warnings
    # 未知 provider 不抛错，回退 mock，保证服务启动和本地开发不被配置错误阻断。
    message = f"Unknown LLM provider `{provider}`; falling back to mock LLM provider"
    LOGGER.warning(message)
    warnings.append(message)
    return MockLLMClient(), warnings


# 函数作用：
# 将 LLM 返回的原始字符串解析为 JSON 对象。
#
# 参数说明：
# - raw：provider 返回的原始文本。
#
# 返回值：
# - 返回普通 dict。
#
# 异常处理：
# - 如果整段不是合法 JSON，会尝试截取第一个 { 到最后一个 } 的内容再解析。
# - 如果解析结果不是对象，会抛 ValueError。
def _parse_json(raw: str) -> JsonDict:
    # strip() 去除模型输出前后的空白和换行。
    text = raw.strip()
    # 首先尝试把完整输出解析为 JSON。
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        # 一些模型会在 JSON 前后加解释文字，这里尝试截取 JSON 对象部分进行修复。
        start = text.find("{")
        end = text.rfind("}")
        # 找不到完整大括号时无法修复，继续抛出原始 JSONDecodeError。
        if start < 0 or end <= start:
            raise
        # 只解析看起来像 JSON 对象的子串。
        value = json.loads(text[start : end + 1])
    # Agent 期望 LLM 返回 JSON object，而不是数组、字符串或数字。
    if not isinstance(value, dict):
        raise ValueError("LLM JSON output must be an object")
    return value


# 函数作用：
# 使用 Pydantic schema 校验 JSON 字典并转换成模型对象。
#
# 参数说明：
# - schema：SummaryLLMOutput、RewriteLLMOutput 或 FeedbackLLMOutput 等模型类。
# - value：解析后的 JSON 字典。
#
# 返回值：
# - 返回 schema 对应的模型实例。
def _validate_schema(schema: type[SchemaT], value: JsonDict) -> SchemaT:
    # Pydantic v2 的 model_validate 会检查字段类型、必填字段和 Field 约束。
    try:
        return schema.model_validate(value)
    except ValidationError:
        # 这里不吞掉错误，因为 _generate_structured 需要捕获它并触发 repair。
        raise


# 函数作用：
# 解析 mock provider 收到的 user_prompt。
#
# 参数说明：
# - user_prompt：LLMTool 序列化后的 JSON 字符串。
#
# 返回值：
# - 返回 dict；如果不是合法 JSON 或不是对象，则返回空字典。
def _load_prompt_payload(user_prompt: str) -> JsonDict:
    # mock provider 不应因为输入不是 JSON 而中断测试流程，所以这里温和解析。
    try:
        value = json.loads(user_prompt)
        # 只有 JSON object 才是预期 payload；其他类型统一视为空对象。
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        # 解析失败返回空字典，让 mock 继续走默认输出。
        return {}
