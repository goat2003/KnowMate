from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional
from pathlib import Path

# 获取项目根目录（.env 文件所在位置）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


class LLMConfig(BaseSettings):
    """LLM 服务配置 (支持 Azure OpenAI 和 标准 OpenAI)"""

    api_key: str = Field(
        default="",
        description="LLM API 密钥"
    )

    base_url: str = Field(
        default="http://192.168.1.56:3000/v1",
        description="LLM API 基础 URL"
    )

    model: str = Field(
        default="gpt-4o-mini",
        description="LLM 模型名称 / Azure 部署名称"
    )

    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="LLM 温度参数"
    )

    max_tokens: Optional[int] = Field(
        default=4096,
        description="最大生成 token 数"
    )

    timeout: int = Field(
        default=60,
        description="请求超时时间（秒）"
    )

    # Azure OpenAI 特定配置
    api_version: Optional[str] = Field(
        default="2024-12-01-preview",
        description="Azure OpenAI API 版本"
    )

    is_azure: bool = Field(
        default=False,
        description="是否使用 Azure OpenAI"
    )

    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore"
    )

# 全局实例化
llm_config = LLMConfig()
