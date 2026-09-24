import asyncio
from app.common.client.embedding_client import get_embedding_client


async def main():
    client = get_embedding_client()

    # 👉 单条文本
    text = "你好，我叫张三"
    embedding = await client.embed(text)

    # print("单条向量长度:", len(embedding))
    # print("前5个值:", embedding[:5])

    # 👉 批量文本
    texts = [
        "今天天气不错",
        "Milvus 是向量数据库",
        "OpenAI embedding 很好用"
    ]

    # embeddings = await client.embed_batch(texts)


    #
    # print(embeddings)
    # print(type(embeddings))
    # print(len(embeddings))
    #
    # print("\n批量结果:")
    # for i, emb in enumerate(embeddings):
    #     print(f"text {i} 向量长度: {len(emb)}")


if __name__ == "__main__":
    asyncio.run(main())
