# 文件作用：
# 本文件封装 milvus-mcp 的向量检索、记忆写入和语义去重工具调用。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 MCP Client 层，主要供 FilterAgent 使用，也为未来 MemoryAgent 写入向量记忆预留方法。
#
# 主要内容：
# 1. MilvusClient 类：提供 search、search_articles、insert_memory_vector、search_similar_memory、semantic_deduplicate。
#
# 关键调用关系：
# - 继承 BaseMcpClient，统一复用权限控制和 mcp_call_logs 生成。
# - FilterAgent 使用 search_similar_memory 判断文章与用户既有记忆是否相关。
#
# 初学者阅读建议：
# 这里的方法名偏业务，内部 tool_name 必须与 MCP Server 暴露的工具名对应。
from __future__ import annotations

from app.contracts import JsonDict
from app.mcp.base_client import BaseMcpClient, McpCallResult


# 类作用：
# MilvusClient 是 milvus-mcp 的专用客户端。
# 它把向量数据库相关工具包装成 Python 方法，减少 Agent 层对 MCP 协议的感知。
class MilvusClient(BaseMcpClient):
    # server_name 用于找到 milvus-mcp endpoint，并写入日志。
    server_name = "milvus-mcp"

    # 函数作用：
    # 根据向量搜索相关文章。
    #
    # 参数说明：
    # - embedding：查询向量。
    # - limit：返回数量上限，默认 3。
    # - agent_name：发起调用的 Agent 名称。
    # - run_id：本次任务 id。
    #
    # 返回值：
    # - 返回 McpCallResult，result 中通常包含 matches。
    def search(self, embedding: list[float], limit: int = 3, *, agent_name: str, run_id: str) -> McpCallResult:
        # search_related_articles 是 MCP Server 侧的工具名。
        return self.call_tool("search_related_articles", {"embedding": embedding, "limit": limit}, agent_name=agent_name, run_id=run_id)

    # 函数作用：
    # 按主题搜索文章。
    #
    # 参数说明：
    # - topic：主题关键词。
    # - limit：返回数量上限。
    # - agent_name：发起调用的 Agent 名称。
    # - run_id：本次任务 id。
    #
    # 返回值：
    # - 返回 McpCallResult。
    def search_articles(self, topic: str = "", limit: int = 3, *, agent_name: str, run_id: str) -> McpCallResult:
        # search_articles 可供摘要或校验阶段获取相似背景材料。
        return self.call_tool("search_articles", {"topic": topic, "limit": limit}, agent_name=agent_name, run_id=run_id)

    # 函数作用：
    # 写入一条记忆向量。
    #
    # 参数说明：
    # - memory_id：记忆记录 id。
    # - embedding：向量值。
    # - metadata：记忆元数据。
    # - agent_name：发起调用的 Agent 名称。
    # - run_id：本次任务 id。
    #
    # 返回值：
    # - 返回 McpCallResult。
    def insert_memory_vector(
        self,
        memory_id: str,
        embedding: list[float],
        metadata: JsonDict | None = None,
        *,
        agent_name: str,
        run_id: str,
    ) -> McpCallResult:
        # metadata or {} 保证 MCP payload 中 metadata 始终是对象。
        return self.call_tool(
            "insert_memory_vector",
            {"id": memory_id, "embedding": embedding, "metadata": metadata or {}},
            agent_name=agent_name,
            run_id=run_id,
        )

    def batch_insert_memory_vectors(
        self,
        items: list[JsonDict],
        *,
        agent_name: str,
        run_id: str,
    ) -> McpCallResult:
        return self.call_tool(
            "batch_insert_memory_vectors",
            {"items": items},
            agent_name=agent_name,
            run_id=run_id,
        )

    def delete_memory_vectors(
        self,
        ids: list[str] | None = None,
        metadata_filter: JsonDict | None = None,
        *,
        agent_name: str,
        run_id: str,
    ) -> McpCallResult:
        return self.call_tool(
            "delete_memory_vectors",
            {"ids": ids or [], "metadata_filter": metadata_filter or {}},
            agent_name=agent_name,
            run_id=run_id,
        )

    # 函数作用：
    # 根据向量搜索相似用户记忆。
    #
    # 参数说明：
    # - embedding：文章或反馈向量。
    # - limit：返回数量上限。
    # - agent_name：发起调用的 Agent 名称。
    # - run_id：本次任务 id。
    #
    # 返回值：
    # - 返回 McpCallResult，FilterAgent 会读取 result["matches"] 决定是否加分。
    def search_similar_memory(
        self,
        embedding: list[float],
        limit: int = 3,
        metadata_filter: JsonDict | None = None,
        minimum_score: float | None = None,
        *,
        agent_name: str,
        run_id: str,
    ) -> McpCallResult:
        # search_similar_memory 与用户长期记忆相关，受 MCPPolicy 控制。
        payload: JsonDict = {"embedding": embedding, "limit": limit, "metadata_filter": metadata_filter or {}}
        if minimum_score is not None:
            payload["minimum_score"] = minimum_score
        return self.call_tool("search_similar_memory", payload, agent_name=agent_name, run_id=run_id)

    # 函数作用：
    # 对候选项做语义去重。
    #
    # 参数说明：
    # - items：待去重对象列表。
    # - threshold：相似度阈值，默认 0.88。
    # - agent_name：发起调用的 Agent 名称。
    # - run_id：本次任务 id。
    #
    # 返回值：
    # - 返回 McpCallResult，通常包含 unique_items 和 duplicates。
    def semantic_deduplicate(self, items: list[JsonDict], threshold: float = 0.88, *, agent_name: str, run_id: str) -> McpCallResult:
        # threshold 越高，只有非常相似的内容才会被判定为重复。
        return self.call_tool("semantic_deduplicate", {"items": items, "threshold": threshold}, agent_name=agent_name, run_id=run_id)
