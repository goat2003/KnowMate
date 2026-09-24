# app/common/embedding_client.py

import logging
import asyncio
from typing import List
import httpx

from app.common.config.embedder_conf import embed_config

logger = logging.getLogger(__name__)


class EmbeddingClient:
    async def embed(self, text: str) -> List[float]:
        raise NotImplementedError

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError

    async def embed_multi_batch(self, text: List[List[str]]) -> List[List[List[float]]]:
        raise NotImplementedError


class OpenAIEmbeddingClient(EmbeddingClient):
    """
    OpenAI / 兼容接口 embedding 客户端
    支持：
    - OpenAI
    - Azure OpenAI
    - 任意兼容 /embeddings 的服务
    """

    def __init__(self):
        self.api_key = embed_config.api_key
        self.base_url = embed_config.base_url.rstrip("/")
        self.model = embed_config.model
        self.dimensions = embed_config.dimensions

        if not self.api_key:
            raise ValueError("EMBEDDING_API_KEY is required")

        logger.info(f"OpenAIEmbeddingClient initialized: model={self.model}")

    async def embed(self, text: str) -> List[float]:
        result = await self.embed_batch([text])
        return result[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        valid_texts = [t for t in texts if t and t.strip()]

        if not valid_texts:
            return [[0.0] * self.dimensions for _ in texts]

        url = f"{self.base_url}/embeddings"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "input": valid_texts,
            # "dimensions": self.dimensions  # 👈 关键
        }

        try:
            result = None
            async with httpx.AsyncClient(timeout=60) as client:
                for attempt in range(3):
                    response = await client.post(url, json=payload, headers=headers)
                    try:
                        response.raise_for_status()
                        result = response.json()
                        break
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code not in {500, 502, 503, 504} or attempt == 2:
                            raise
                        wait_time = 2 ** attempt
                        logger.warning(
                            "Embedding service returned %s, retrying in %ss (%s/3)",
                            e.response.status_code,
                            wait_time,
                            attempt + 1,
                        )
                        await asyncio.sleep(wait_time)

            if result is None:
                raise RuntimeError("Embedding request failed without response data")

            embeddings = [item["embedding"] for item in result["data"]]

            # 对齐原输入顺序
            result_list = []
            idx = 0
            for t in texts:
                if t and t.strip():
                    result_list.append(embeddings[idx])
                    idx += 1
                else:
                    result_list.append([0.0] * len(embeddings[0]))

            return result_list

        except httpx.HTTPStatusError as e:
            logger.error(
                "Embedding failed: status=%s url=%s model=%s response=%s",
                e.response.status_code,
                url,
                self.model,
                e.response.text[:1000],
            )
            raise
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            raise

    # 单独计算两个向量之间的距离，用于实体节点语义匹配
    # 此处 使用的是 余弦相似度
    async def distance(self, text1: str, text2: str) -> float:
        v1 = await self.embed(text1)
        v2 = await self.embed(text2)

        # L1
        from sklearn.metrics.pairwise import cosine_similarity
        distance = cosine_similarity([v1], [v2])[0][0]

        # Cosine Similarity（余弦相似度）越大，表示越相似。
        # 范围通常是：-1 ~ 1 之间
        # 但对于 OpenAI 的文本 Embedding，实际几乎总是在：0 ~ 1 之间。

        return distance

    async def distance_loop(self, test_pairs):
        for text1, text2, expected in test_pairs:
            distance = await self.distance(text1, text2)
            print(text1, text2, distance)



def get_embedding_client() -> EmbeddingClient:
    return OpenAIEmbeddingClient()

if __name__ == "__main__":
    import asyncio
    client = get_embedding_client()
    # v1 = asyncio.run(client.embed("hello world"))
    # print(len(v1))
    test_pairs1 = [
        # 高相似
        ("旅游地点", "旅行地点", "high"),
        ("母亲", "妈妈", "high"),
        ("朋友", "好友", "high"),
        ("闺蜜", "最好的朋友", "high"),
        ("买房", "购房", "high"),
        ("退款申请", "退货申请", "high"),
        ("人工智能", "AI", "high"),
        ("电动汽车", "新能源汽车", "high"),
        ("手机号码", "联系电话", "high"),
        ("电子邮箱", "邮箱地址", "high"),

        # 中等相似
        ("医生", "医院", "medium"),
        ("学生", "学校", "medium"),
        ("飞机", "机场", "medium"),
        ("程序员", "软件开发", "medium"),
        ("篮球", "NBA", "medium"),
        ("火车", "高铁", "medium"),
        ("咖啡", "星巴克", "medium"),
        ("北京", "故宫", "medium"),
        ("苹果公司", "iPhone", "medium"),
        ("健身", "跑步", "medium"),

        # 低相似
        ("苹果", "香蕉", "low"),
        ("汽车", "自行车", "low"),
        ("老师", "校长", "low"),
        ("狗", "猫", "low"),
        ("小说", "电影", "low"),
        ("银行", "保险", "low"),
        ("电脑", "打印机", "low"),
        ("上海", "广州", "low"),
        ("游泳", "足球", "low"),
        ("微信", "支付宝", "low"),

        # 无关
        ("母亲", "火箭发动机", "none"),
        ("闺蜜", "数据库索引", "none"),
        ("旅游地点", "TCP协议", "none"),
        ("苹果", "量子力学", "none"),
        ("医院", "区块链", "none"),
        ("飞机", "红烧肉", "none"),
        ("咖啡", "操作系统", "none"),
        ("北京", "神经网络", "none"),
        ("篮球", "分布式事务", "none"),
        ("手机", "核聚变反应堆", "none"),
    ]

    test_pairs = [
        # 高相似
        ("Dog", "Pet", "high")
    ]
    asyncio.run(client.distance_loop(test_pairs))





    # result = asyncio.run(client.embed_batch([["hello world"]]))
