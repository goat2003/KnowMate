from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional
from pathlib import Path

# 获取项目根目录（.env 文件所在位置）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


class EmbedConfig(BaseSettings):
    """ OpenAI 配置"""

    api_key: str = Field(
        default="",
        description="BigModel API 密钥"
    )

    base_url: str = Field(
        default="https://open.bigmodel.cn/api/paas/v4",
        description="API 基础 URL"
    )

    model: str = Field(
        default="text-embedding-3-small",
        description="Embedding 模型名称"
    )

    dimensions: int = Field(
        default=1024,
        description="向量维度 (支持自定义)"
    )

    timeout: int = Field(
        default=30,
        description="请求超时时间（秒）"
    )

    enabled: bool = Field(
        default=True,
        description="是否启用 text-embedding-3-small"
    )

    model_config = SettingsConfigDict(
        env_prefix="EMBEDDING_",
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore"
    )



embed_config = EmbedConfig()
