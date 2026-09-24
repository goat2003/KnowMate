"""
LLM 客户端模块

支持:
- 标准 OpenAI API
- 自定义 OpenAI 兼容端点
- JSON 模式输出
- 自动重试
- Token 统计
"""

import json
import logging
import asyncio
import sys
from pathlib import Path
from typing import Dict, Any, Optional, Union, List
from dataclasses import dataclass
# import logger
from openai import AsyncOpenAI, OpenAIError, APIError, RateLimitError, APITimeoutError
from app.common.config.llm_conf import llm_config

logger = logging.getLogger(__name__)

@dataclass
class LLMResponse:
    """LLM 响应数据类"""
    content: Union[str, Dict[str, Any]]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    finish_reason: str = ""

    @property
    def is_json(self) -> bool:
        """判断返回内容是否为 JSON"""
        return isinstance(self.content, dict)


class LLMClient:
    """
    LLM 客户端 (支持标准 OpenAI 和兼容 API)
    """

    # 用来存“唯一实例”（单例）
    _instance: Optional["LLMClient"] = None
    # 真正调用 API 的对象
    _client: Optional[AsyncOpenAI] = None
    # 标记“是否已经初始化过”
    _initialized: bool = False

    # 控制“对象创建”  所有调用都返回同一个实例
    # 核心逻辑：
    # 第一次 → 创建对象
    # 后续 → 直接返回已有对象
    def __new__(cls) -> "LLMClient":
        """实现单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化客户端（只执行一次）"""
        # 防止重复初始化
        if not self._initialized:
            self._initialize_client()
            # 初始化一次后锁死
            self._initialized = True

    def _initialize_client(self):
        """初始化 OpenAI 客户端"""
        try:
            # 统一使用标准 OpenAI 客户端
            self._client = AsyncOpenAI(
                api_key=llm_config.api_key,
                base_url=llm_config.base_url,
                timeout=llm_config.timeout,
            )
            # print("api_key: ", llm_config.api_key)
            logger.info(f"✅ OpenAI Client 初始化成功 (Base URL: {llm_config.base_url}, Model: {llm_config.model})")

        except Exception as e:
            logger.error(f"❌ LLM Client 初始化失败: {e}")
            raise

    async def chat(
        self,
        prompt: str = "",
        system_prompt: str = "You are a helpful assistant.",
        json_mode: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        max_retries: int = 3,
        **kwargs
    ) -> LLMResponse:
        """
        发送对话请求

        Args:
            prompt: 用户输入
            system_prompt: 系统提示词
            json_mode: 是否强制返回 JSON 格式
            temperature: 本次调用的温度，不传则使用默认值
            max_tokens: 最大生成 token 数，不传则使用默认值
            messages: 完整的消息列表（如果提供，则忽略 prompt 和 system_prompt）
            max_retries: 最大重试次数
            **kwargs: 其他 OpenAI API 参数

        Returns:
            LLMResponse: 包含响应内容和 token 统计信息
        """
        # 初始化检查
        if self._client is None:
            raise RuntimeError("LLM Client not initialized")

        # 构造消息
        if messages is None:
            # 两种模式
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]

        # 如果开启 JSON 模式，确保 System Prompt 里包含 "JSON" 字样
        if json_mode:
            if "json" not in messages[0]["content"].lower():
                messages[0]["content"] += " Please respond in JSON format."

        # 构造参数
        params = {
            "model": llm_config.model,
            "messages": messages,
            "max_tokens": max_tokens if max_tokens is not None else llm_config.max_tokens,
            "temperature": temperature if temperature is not None else llm_config.temperature,
            **kwargs
        }

        # 如果开启 JSON 模式
        if json_mode:
            params["response_format"] = {"type": "json_object"}

        # 重试逻辑
        last_error = None
        for attempt in range(max_retries):
            try:
                response = await self._client.chat.completions.create(**params)
                content = response.choices[0].message.content

                # 解析内容
                parsed_content: Union[str, Dict[str, Any]] = content
                if json_mode:
                    try:
                        parsed_content = json.loads(content)
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ 模型返回的不是有效的 JSON: {content[:200]}")
                        parsed_content = {}

                # 构造响应对象
                return LLMResponse(
                    content=parsed_content,
                    prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                    completion_tokens=response.usage.completion_tokens if response.usage else 0,
                    total_tokens=response.usage.total_tokens if response.usage else 0,
                    model=response.model,
                    finish_reason=response.choices[0].finish_reason
                )

            # 异常处理
            # 限流
            except RateLimitError as e:
                last_error = e
                wait_time = 2 ** attempt  # 指数退避
                logger.warning(f"⚠️ 触发速率限制，等待 {wait_time}s 后重试 (尝试 {attempt + 1}/{max_retries})")
                await asyncio.sleep(wait_time)
            # 超时
            except APITimeoutError as e:
                last_error = e
                logger.warning(f"⚠️ 请求超时，重试中 (尝试 {attempt + 1}/{max_retries})")
                await asyncio.sleep(1)
            # API 错误
            except APIError as e:
                last_error = e
                logger.error(f"❌ API 错误: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                else:
                    break
            # SDK 错误
            except OpenAIError as e:
                last_error = e
                logger.error(f"❌ OpenAI 错误: {e}")
                break
            # 未知错误
            except Exception as e:
                last_error = e
                logger.error(f"❌ 未知错误: {e}")
                break

        # 所有重试都失败
        logger.error(f"❌ LLM API 调用失败，已重试 {max_retries} 次: {last_error}")
        # 不抛异常，返回错误结果
        return LLMResponse(
            content={} if json_mode else f"Error: {str(last_error)}",
            model=llm_config.model
        )



    def chat_sync(
        self,
        prompt: str = "",
        system_prompt: str = "You are a helpful assistant.",
        json_mode: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        **kwargs
    ) -> LLMResponse:
        """
        同步版本的对话请求（用于非异步环境）

        Args:
            同 chat() 方法

        Returns:
            LLMResponse: 包含响应内容和 token 统计信息
        """
        return asyncio.run(
            self.chat(
                prompt=prompt,
                system_prompt=system_prompt,
                json_mode=json_mode,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=messages,
                **kwargs
            )
        )

    @classmethod
    def get_instance(cls) -> "LLMClient":
        """
        获取单例实例

        Returns:
            LLMClient: 全局唯一实例
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def close(self):
        """关闭客户端连接"""
        if self._client is not None:
            await self._client.close()
            logger.info("✅ LLM Client 已关闭")
# 全局实例获取函数
async def get_llm_client() -> LLMClient:
    """
    获取 LLM 客户端实例（用于依赖注入）

    Returns:
        LLMClient: 全局唯一实例
    """
    return LLMClient.get_instance()