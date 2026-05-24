# 文件作用：
# 本文件集中导出 MCP Client 层的公共类，方便其他模块从 app.mcp 统一导入。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 MCP Client 包入口。
#
# 主要内容：
# 1. 导出 BaseMcpClient、各具体 MCP Client、传输层和 MCPPolicy。
#
# 关键调用关系：
# - 被 app.workflow.graph 引用，用于一次性导入 EmbeddingClient、FetchClient、MilvusClient、Neo4jClient 等。
#
# 初学者阅读建议：
# 这里没有业务逻辑；如果要理解 MCP 调用过程，请优先阅读 base_client.py 和 policy.py。
from .base_client import BaseMcpClient, JsonRpcMcpTransport, McpCallResult, MockMcpTransport
from .embedding_client import EmbeddingClient
from .fetch_client import FetchClient
from .milvus_client import MilvusClient
from .neo4j_client import Neo4jClient
from .policy import DEFAULT_AGENT_TOOL_PERMISSIONS, MCPPolicy

# __all__ 声明包对外公开的符号。
# 这样 ArticleWorkflow 可以写 from app.mcp import EmbeddingClient，而不需要知道具体文件路径。
__all__ = [
    "BaseMcpClient",
    "EmbeddingClient",
    "FetchClient",
    "JsonRpcMcpTransport",
    "McpCallResult",
    "MilvusClient",
    "MockMcpTransport",
    "Neo4jClient",
    "MCPPolicy",
    "DEFAULT_AGENT_TOOL_PERMISSIONS",
]
