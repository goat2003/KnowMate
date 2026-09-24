# app/topic/embedding_adapter.py
import numpy as np
from typing import List

from app.common.client.embedding_client import get_embedding_client


class EmbeddingAdapter:
    """
    将 async embedding client 转为同步接口（供 BERTopic 使用）
    """

    def __init__(self):
        self.client = get_embedding_client()

    async def embed_documents(self, docs: List[str]) -> np.ndarray:
        """
        同步调用（给 BERTopic）
        """
        embeddings = await self.client.embed_batch(docs)
        return np.array(embeddings)

    async def _embed_async(self, docs: List[str]) -> np.ndarray:
        embeddings = await self.client.embed_batch(docs)
        return np.array(embeddings)
