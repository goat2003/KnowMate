# 文件作用：
# 本文件实现 milvus-mcp 服务，负责向量记忆写入、相似记忆检索、相关文章检索和语义去重。
# 当前实现使用进程内 MEMORY_STORE 做 mock 向量库，不连接真实 Milvus；配置中保留了 milvus_uri 和 collection。
#
# 在项目中的位置：
# 本文件属于 MCP Server 层，被 Python Agent 的 MilvusClient 通过 JSON-RPC 调用。
#
# 主要内容：
# 1. CONFIG：读取 mock 和 Milvus 配置。
# 2. MEMORY_STORE：进程内模拟向量库。
# 3. TOOLS：声明 insert_memory_vector、search_similar_memory、search_related_articles、search_articles、semantic_deduplicate。
# 4. handle：分发 MCP 工具调用。
# 5. _cosine / _jaccard：提供相似度计算。
#
# 关键调用关系：
# - FilterAgent 调用 search_similar_memory 判断文章是否与用户记忆相关。
# - 未来 MemoryAgent 可调用 insert_memory_vector 写入长期记忆。
#
# 初学者阅读建议：
# 注意当前 MEMORY_STORE 是内存 mock，服务重启后会丢失；不要把它理解为真实 Milvus 持久化。
from __future__ import annotations

import math
import os
from pathlib import Path
import sys
from uuid import uuid4

# 将公共 MCP 框架加入导入路径。
sys.path.append(str(Path(__file__).resolve().parents[1] / "common"))

from simple_http_mcp import (  # noqa: E402
    ToolError,
    ToolSpec,
    optional_number_list,
    require_object,
    require_str,
    run_server,
)


# CONFIG 保存服务模式和真实 Milvus 预留配置。
CONFIG = {
    "mock_mode": os.getenv("MILVUS_MOCK_MODE", "true").lower() != "false",
    "milvus_uri": os.getenv("MILVUS_URI", "http://127.0.0.1:19530"),
    "collection": os.getenv("MILVUS_COLLECTION", "knowledge_memory"),
}

# MEMORY_STORE 是 mock 向量库，key 是 memory_id，value 保存 embedding 和 metadata。
MEMORY_STORE: dict[str, dict[str, object]] = {}

# TOOLS 声明 milvus-mcp 对外暴露的工具。
TOOLS = [
    # 写入或更新一条记忆向量。
    ToolSpec(
        name="insert_memory_vector",
        description="Insert or update one memory vector in the in-memory mock vector store.",
        input_schema={"type": "object", "required": ["id", "embedding"], "properties": {"id": {"type": "string"}, "embedding": {"type": "array"}, "metadata": {"type": "object"}}},
        output_schema={"type": "object", "properties": {"upserted": {"type": "boolean"}, "id": {"type": "string"}}},
        examples=[{"request": {"id": "m1", "embedding": [0.1, 0.2], "metadata": {"topic": "AI"}}, "response": {"upserted": True, "id": "m1"}}],
    ),
    # 根据向量搜索相似记忆。
    ToolSpec(
        name="search_similar_memory",
        description="Search the in-memory mock vector store for similar memory vectors.",
        input_schema={"type": "object", "required": ["embedding"], "properties": {"embedding": {"type": "array"}, "limit": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {"matches": {"type": "array"}}},
        examples=[{"request": {"embedding": [0.1, 0.2], "limit": 3}, "response": {"matches": [{"id": "m1", "score": 1.0}]}}],
    ),
    # 根据向量或主题返回相关文章。
    ToolSpec(
        name="search_related_articles",
        description="Return mock related articles for an embedding or topic.",
        input_schema={"type": "object", "properties": {"embedding": {"type": "array"}, "topic": {"type": "string"}, "limit": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {"matches": {"type": "array"}}},
        examples=[{"request": {"topic": "AI"}, "response": {"matches": [{"article_id": "mock-related-1", "score": 0.81}]}}],
    ),
    # search_articles 是预留给 Summary Agent 检索背景材料的别名工具。
    ToolSpec(
        name="search_articles",
        description="Return mock articles for a topic query. This is an alias reserved for Summary Agent retrieval.",
        input_schema={"type": "object", "properties": {"topic": {"type": "string"}, "limit": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {"matches": {"type": "array"}}},
        examples=[{"request": {"topic": "AI"}, "response": {"matches": [{"article_id": "mock-related-1", "score": 0.81}]}}],
    ),
    # 语义去重工具，用简单 Jaccard 相似度模拟。
    ToolSpec(
        name="semantic_deduplicate",
        description="Group semantically duplicate candidate articles by text similarity.",
        input_schema={"type": "object", "required": ["items"], "properties": {"items": {"type": "array"}, "threshold": {"type": "number"}}},
        output_schema={"type": "object", "properties": {"unique_items": {"type": "array"}, "duplicate_groups": {"type": "array"}}},
        examples=[{"request": {"items": [{"id": "a1", "text": "AI note"}]}, "response": {"unique_items": ["a1"], "duplicate_groups": []}}],
    ),
]


# 函数作用：
# MCP 工具分发入口。
#
# 参数说明：
# - tool：工具名。
# - payload：工具参数。
#
# 返回值：
# - 返回工具输出字典。
def handle(tool: str, payload: dict[str, object]) -> dict[str, object]:
    # 写入记忆向量。
    if tool == "insert_memory_vector":
        return _insert_memory_vector(payload)
    # 搜索相似记忆。
    if tool == "search_similar_memory":
        embedding = optional_number_list(payload, "embedding")
        limit = _limit(payload)
        return {"matches": _search_store(embedding, limit), "mock": CONFIG["mock_mode"]}
    # 相关文章检索和文章检索共用一套 mock 逻辑。
    if tool in {"search_related_articles", "search_articles"}:
        # 没传 embedding 时使用默认向量，保证 mock 检索仍能返回内容。
        embedding = optional_number_list(payload, "embedding", [0.31, 0.27, 0.93])
        limit = _limit(payload)
        matches = _search_store(embedding, limit)
        # 内存库没有结果时按 topic 生成固定相关文章。
        if not matches:
            topic = str(payload.get("topic", "general"))
            matches = [
                {"article_id": f"mock-related-{idx}", "title": f"{topic} related article {idx}", "score": round(0.92 - idx * 0.07, 4)}
                for idx in range(1, limit + 1)
            ]
        return {"matches": matches, "mock": CONFIG["mock_mode"]}
    # 语义去重。
    if tool == "semantic_deduplicate":
        return _semantic_deduplicate(payload)
    raise ToolError(f"unknown tool `{tool}`", code=-32601)


# 函数作用：
# 写入或更新一条 mock 记忆向量。
def _insert_memory_vector(payload: dict[str, object]) -> dict[str, object]:
    # memory_id 是记忆主键。
    memory_id = require_str(payload, "id")
    # embedding 必须是数字数组。
    embedding = optional_number_list(payload, "embedding")
    # metadata 必须是对象，缺失时为空对象。
    metadata = require_object(payload, "metadata", {})
    # 空向量无法做相似度计算，直接报参数错误。
    if not embedding:
        raise ToolError("`embedding` cannot be empty", data={"field": "embedding"})
    # upsert 到进程内 map。
    MEMORY_STORE[memory_id] = {"id": memory_id, "embedding": embedding, "metadata": metadata}
    return {"upserted": True, "id": memory_id, "count": len(MEMORY_STORE), "mock": CONFIG["mock_mode"]}


# 函数作用：
# 在 mock 向量库中搜索最相似的记忆。
def _search_store(embedding: list[float], limit: int) -> list[dict[str, object]]:
    # 首次查询时写入种子数据，避免空库导致演示无结果。
    if not MEMORY_STORE:
        _seed_store()
    # scored 保存带相似度的候选。
    scored = []
    for memory in MEMORY_STORE.values():
        # type ignore 是因为 memory["embedding"] 的静态类型是 object，运行时实际是 list[float]。
        score = _cosine(embedding, memory["embedding"])  # type: ignore[arg-type]
        scored.append({"id": memory["id"], "score": round(score, 6), "metadata": memory["metadata"]})
    # 按分数降序排列。
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


# 函数作用：
# 使用简单文本指纹和 Jaccard 相似度做语义去重 mock。
def _semantic_deduplicate(payload: dict[str, object]) -> dict[str, object]:
    # items 必须是数组。
    items = payload.get("items")
    if not isinstance(items, list):
        raise ToolError("`items` must be an array", data={"field": "items"})
    # threshold 是判定重复的相似度阈值。
    threshold = float(payload.get("threshold", 0.88) or 0.88)
    # unique 保存唯一项 id。
    unique: list[str] = []
    # duplicate_groups 保存重复关系。
    duplicate_groups: list[dict[str, object]] = []
    # fingerprints 保存每个唯一项的文本指纹。
    fingerprints: dict[str, str] = {}
    for raw in items:
        if not isinstance(raw, dict):
            raise ToolError("each item must be an object", data={"field": "items"})
        # id 缺失时生成随机 id。
        item_id = str(raw.get("id") or uuid4().hex)
        # text 优先使用 text，其次 title。
        text = str(raw.get("text") or raw.get("title") or "")
        # 指纹使用去重后的词集合排序拼接，模拟语义近似。
        fingerprint = " ".join(sorted(set(text.lower().split())))
        # 查找已有唯一项中是否有 Jaccard 达到阈值的项。
        duplicate_of = next((existing for existing, fp in fingerprints.items() if _jaccard(fp, fingerprint) >= threshold), "")
        if duplicate_of:
            duplicate_groups.append({"canonical_id": duplicate_of, "duplicate_id": item_id, "score": _jaccard(fingerprints[duplicate_of], fingerprint)})
        else:
            unique.append(item_id)
            fingerprints[item_id] = fingerprint
    return {"unique_items": unique, "duplicate_groups": duplicate_groups, "threshold": threshold, "mock": CONFIG["mock_mode"]}


# 函数作用：
# 初始化 mock 向量库种子数据。
def _seed_store() -> None:
    MEMORY_STORE["seed-ai"] = {"id": "seed-ai", "embedding": [0.2, 0.4, 0.6], "metadata": {"topic": "AI"}}
    MEMORY_STORE["seed-kg"] = {"id": "seed-kg", "embedding": [0.1, 0.8, 0.3], "metadata": {"topic": "knowledge-graph"}}


# 函数作用：
# 计算两个向量的余弦相似度。
def _cosine(a: list[float], b: list[float]) -> float:
    # 使用两个向量较短的长度，兼容维度不一致的 mock 输入。
    size = min(len(a), len(b))
    if size == 0:
        return 0.0
    # 点积。
    dot = sum(a[idx] * b[idx] for idx in range(size))
    # 两个向量的 L2 范数。
    norm_a = math.sqrt(sum(value * value for value in a[:size]))
    norm_b = math.sqrt(sum(value * value for value in b[:size]))
    # 任一范数为 0 时无法计算余弦相似度，返回 0。
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


# 函数作用：
# 计算两个文本指纹的 Jaccard 相似度。
def _jaccard(left: str, right: str) -> float:
    a = set(left.split())
    b = set(right.split())
    # 两边都为空时视为完全相同。
    if not a and not b:
        return 1.0
    return len(a & b) / max(len(a | b), 1)


# 函数作用：
# 解析并限制 limit 参数。
def _limit(payload: dict[str, object]) -> int:
    limit = int(payload.get("limit", 3) or 3)
    # 限制范围 1..20，避免 mock 服务返回过多数据。
    return max(1, min(limit, 20))


# 直接运行本文件时启动 milvus-mcp。
if __name__ == "__main__":
    run_server("milvus-mcp", int(os.getenv("PORT", "7003")), TOOLS, handle, CONFIG)
