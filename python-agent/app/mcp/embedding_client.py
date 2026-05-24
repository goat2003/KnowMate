# 文件作用：
# 本文件封装 embedding-mcp 的工具调用，负责把文本转换成向量。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 MCP Client 层，被 FilterAgent 和 MemoryAgent 使用。
#
# 主要内容：
# 1. EmbeddingClient 类：提供 embed_text 和 embed_batch 两个便捷方法。
#
# 关键调用关系：
# - 继承 BaseMcpClient，实际权限检查、传输调用和日志生成都在 BaseMcpClient.call_tool 中完成。
# - FilterAgent 用 embed_text 为文章生成向量。
# - MemoryAgent 用 embed_text 为反馈生成向量。
#
# 初学者阅读建议：
# 这里每个方法只是把 Python 参数整理成 MCP Tool 需要的 payload，真正调用流程请看 base_client.py。
from __future__ import annotations

from app.contracts import JsonDict
from app.mcp.base_client import BaseMcpClient, McpCallResult


# 类作用：
# EmbeddingClient 是 embedding-mcp 的专用客户端。
# 它把通用 call_tool 包装成更清晰的业务方法。
class EmbeddingClient(BaseMcpClient):
    # server_name 会写入 MCP JSON-RPC endpoint 匹配和 mcp_call_logs。
    server_name = "embedding-mcp"

    # 函数作用：
    # 调用 embed_text 工具，把单段文本转换为向量。
    #
    # 参数说明：
    # - text：待向量化文本，可以是文章标题+正文或反馈文本。
    # - metadata：可选元数据，例如 {"source": "feedback"}。
    # - agent_name：发起调用的 Agent 名称，用于 MCPPolicy 权限检查。
    # - run_id：本次任务 id，用于日志关联。
    #
    # 返回值：
    # - 返回 McpCallResult，result 中通常包含 embedding 和 dim，log 中包含调用日志。
    def embed_text(
        self,
        text: str,
        metadata: JsonDict | None = None,
        *,
        agent_name: str,
        run_id: str,
    ) -> McpCallResult:
        # metadata or {} 保证传给 MCP 的 metadata 一定是字典，而不是 None。
        return self.call_tool("embed_text", {"text": text, "metadata": metadata or {}}, agent_name=agent_name, run_id=run_id)

    # 函数作用：
    # 调用 embed_batch 工具，把多段文本一次性转换为向量列表。
    #
    # 参数说明：
    # - texts：待向量化文本列表。
    # - metadata：批量请求共享的元数据。
    # - agent_name：发起调用的 Agent 名称。
    # - run_id：本次任务 id。
    #
    # 返回值：
    # - 返回 McpCallResult，result 中通常包含 embeddings 和 dim。
    def embed_batch(
        self,
        texts: list[str],
        metadata: JsonDict | None = None,
        *,
        agent_name: str,
        run_id: str,
    ) -> McpCallResult:
        # 这里不直接访问 transport，而是走 BaseMcpClient.call_tool，以确保权限和日志统一生效。
        return self.call_tool(
            "embed_batch",
            {"texts": texts, "metadata": metadata or {}},
            agent_name=agent_name,
            run_id=run_id,
        )
