# 文件作用：
# 本文件实现 embedding-mcp 服务，负责把文本转换为向量。
# 当前实现是确定性的 mock embedding，不调用真实模型；配置中预留了真实 embedding endpoint 字段。
#
# 在项目中的位置：
# 本文件属于 MCP Server 层，被 Python Agent 的 EmbeddingClient 通过 JSON-RPC 调用。
#
# 主要内容：
# 1. CONFIG：读取 embedding 维度和 mock 配置。
# 2. TOOLS：声明 embed_text 和 embed_batch 工具。
# 3. handle：根据工具名分发请求。
# 4. _embed_one：用 SHA-256 生成稳定 mock 向量。
#
# 关键调用关系：
# - Python Agent FilterAgent 用 embed_text 为文章生成向量。
# - Python Agent MemoryAgent 用 embed_text 为反馈生成向量。
#
# 初学者阅读建议：
# 注意这里的向量是 mock 逻辑，只保证稳定和可测试，不代表真实语义 embedding。
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys

# 将 mcp-servers/common 加入导入路径，使本服务能导入 simple_http_mcp。
sys.path.append(str(Path(__file__).resolve().parents[1] / "common"))

from simple_http_mcp import ToolError, ToolSpec, require_str, run_server  # noqa: E402


# DIMENSION 控制 mock 向量维度，默认 8。
DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "8"))
# CONFIG 会在 /health 中返回，帮助调用方确认服务模式。
CONFIG = {
    "mock_mode": os.getenv("EMBEDDING_MOCK_MODE", "true").lower() != "false",
    "real_embedding_endpoint": os.getenv("REAL_EMBEDDING_ENDPOINT", ""),
    "dimension": DIMENSION,
}

# TOOLS 是本 MCP Server 对外暴露的工具清单。
TOOLS = [
    # embed_text 处理单段文本。
    ToolSpec(
        name="embed_text",
        description="Create a deterministic mock embedding for one text input.",
        input_schema={"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}},
        output_schema={
            "type": "object",
            "properties": {
                "embedding": {"type": "array", "items": {"type": "number"}},
                "dim": {"type": "integer"},
                "model": {"type": "string"},
                "mock": {"type": "boolean"},
            },
        },
        examples=[
            {
                "request": {"text": "agent workflow"},
                "response": {"embedding": [0.1961, 0.5333], "dim": DIMENSION, "model": "mock-hash-embedding-v1"},
            }
        ],
    ),
    # embed_batch 批量处理多段文本。
    ToolSpec(
        name="embed_batch",
        description="Create deterministic mock embeddings for multiple text inputs.",
        input_schema={"type": "object", "required": ["texts"], "properties": {"texts": {"type": "array"}}},
        output_schema={"type": "object", "properties": {"items": {"type": "array"}, "dim": {"type": "integer"}}},
        examples=[
            {
                "request": {"texts": ["agent workflow", "knowledge memory"]},
                "response": {"items": [{"index": 0, "embedding": [0.1961, 0.5333]}], "dim": DIMENSION},
            }
        ],
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
    # embed_text 要求 text 字段是字符串。
    if tool == "embed_text":
        text = require_str(payload, "text")
        return _embed_one(text)
    # embed_batch 要求 texts 是字符串数组。
    if tool == "embed_batch":
        texts = payload.get("texts")
        if not isinstance(texts, list):
            raise ToolError("`texts` must be an array of strings", data={"field": "texts"})
        # 字典展开 **_embed_one(...) 会把 embedding/dim/model/mock 合并进每个 item。
        return {"items": [{"index": idx, **_embed_one(str(text))} for idx, text in enumerate(texts)], "dim": DIMENSION}
    # 未知工具返回 JSON-RPC method not found。
    raise ToolError(f"unknown tool `{tool}`", code=-32601)


# 函数作用：
# 为单段文本生成确定性 mock embedding。
#
# 参数说明：
# - text：待向量化文本。
#
# 返回值：
# - 返回包含 embedding、dim、model、mock 的字典。
def _embed_one(text: str) -> dict[str, object]:
    # SHA-256 摘要稳定，同一文本每次得到同一向量，方便测试。
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # values 保存 [-1, 1] 范围内的浮点向量。
    values = []
    # 如果 DIMENSION 大于 digest 长度，就用取模循环使用摘要字节。
    for idx in range(DIMENSION):
        byte = digest[idx % len(digest)]
        # byte/255 映射到 0..1，再转换到 -1..1。
        values.append(round((byte / 255.0) * 2 - 1, 6))
    return {
        "embedding": values,
        "dim": DIMENSION,
        "model": "mock-hash-embedding-v1",
        "mock": CONFIG["mock_mode"],
    }


# 直接运行本文件时启动 HTTP MCP Server。
if __name__ == "__main__":
    run_server("embedding-mcp", int(os.getenv("PORT", "7001")), TOOLS, handle, CONFIG)
