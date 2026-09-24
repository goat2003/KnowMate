from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional
from pathlib import Path

# 获取项目根目录（.env 文件所在位置）
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


class RerankerConfig(BaseSettings):
    """智谱AI BigModel Reranker 配置

    API Key 和 Base URL 默认复用 BigModel (Embedding) 配置，
    无需重复设置。如需独立配置，可通过 RERANKER_API_KEY / RERANKER_BASE_URL 覆盖。
    """

    api_key: str = Field(
        default="",
        description="Reranker API 密钥（留空则复用 BIGMODEL_API_KEY）"
    )

    base_url: str = Field(
        default="",
        description="Reranker API 基础 URL（留空则复用 BIGMODEL_BASE_URL）"
    )

    model: str = Field(
        default="rerank",
        description="重排序模型名称"
    )

    top_n: int = Field(
        default=0,
        description="返回得分最高的前 n 条结果（0 = 返回所有）"
    )

    return_documents: bool = Field(
        default=False,
        description="是否在响应中返回原始文本"
    )

    return_raw_scores: bool = Field(
        default=False,
        description="是否返回原始分数"
    )

    timeout: int = Field(
        default=30,
        description="请求超时时间（秒）"
    )

    enabled: bool = Field(
        default=True,
        description="是否启用 Reranker"
    )

    model_config = SettingsConfigDict(
        env_prefix="RERANKER_",
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def get_api_key(self) -> str:
        """获取 API Key，优先使用 RERANKER_API_KEY，否则回退到 EMBEDDING_API_KEY"""
        if self.api_key:
            return self.api_key
        from app.common.config.embedder_conf import embed_config
        return embed_config.api_key

    def get_base_url(self) -> str:
        """获取 Base URL，优先使用 RERANKER_BASE_URL，否则回退到 EMBEDDING_BASE_URL"""
        if self.base_url:
            return self.base_url
        from app.common.config.embedder_conf import embed_config
        return embed_config.base_url


reranker_config = RerankerConfig()
