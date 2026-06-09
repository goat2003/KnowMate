# 文件作用：
# 本文件定义 MCP 工具调用权限策略，控制不同 Agent 能调用哪些 MCP Tool。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 MCP Client 层，是 MCP 权限控制的核心配置和判断逻辑。
#
# 主要内容：
# 1. DEFAULT_AGENT_TOOL_PERMISSIONS：默认 Agent -> Tool 白名单。
# 2. MCPPermissionDecision：权限判断结果对象。
# 3. MCPPolicy：执行权限判断、查询允许工具列表、规范化 Agent 名称。
#
# 关键调用关系：
# - 被 BaseMcpClient.call_tool 调用。
# - 间接影响 FilterAgent、MemoryAgent 等是否能成功调用 MCP 工具。
#
# 初学者阅读建议：
# 先看 DEFAULT_AGENT_TOOL_PERMISSIONS 理解“权限白名单”，
# 再看 MCPPolicy.check 如何把未授权调用转换为可记录的拒绝结果。
from __future__ import annotations

from dataclasses import dataclass


HIGH_RISK_TOOLS: set[str] = {
    "send_email",
    "save_markdown",
    "write_file",
    "read_file",
    "delete_file",
    "generate_daily_report",
    "generate_weekly_report",
}


# DEFAULT_AGENT_TOOL_PERMISSIONS 是 MCP 权限白名单。
# key 是 Agent 名称，value 是该 Agent 允许调用的 MCP Tool 名称集合。
# 这张表的作用是防止某个 Agent 越权调用与自己职责无关的工具。
DEFAULT_AGENT_TOOL_PERMISSIONS: dict[str, set[str]] = {
    # filter Agent 需要 embedding、Milvus 和 Neo4j 上下文来判断文章是否匹配用户兴趣。
    "filter": {
        "embed_text",
        "embed_batch",
        "search_similar_memory",
        "query_user_interest_graph",
        "get_related_topics",
    },
    # summary Agent 理论上只需要读取内容类工具，不允许写记忆。
    "summary": {
        "fetch_webpage",
        "extract_main_content",
        "search_articles",
    },
    # check Agent 可访问原文和相似性工具，用于校验链接、重复内容或事实上下文。
    "check": {
        "fetch_webpage",
        "check_url_alive",
        "search_similar_memory",
        "semantic_deduplicate",
    },
    # feedback Agent 可以做轻量语义检索，但不直接修改长期记忆。
    "feedback": {
        "embed_text",
        "search_similar_memory",
    },
    # memory Agent 负责更新用户画像和记忆，因此允许写入向量和兴趣图谱。
    "memory": {
        "embed_text",
        "insert_memory_vector",
        "batch_insert_memory_vectors",
        "delete_memory_vectors",
        "search_similar_memory",
        "update_user_interest_graph",
        "query_user_interest_graph",
        "get_related_topics",
    },
    # output Agent 当前代码中未实现，但权限表预留了报告、邮件和 Markdown 输出工具。
    "output": set(),
}


# 类作用：
# MCPPermissionDecision 表示一次权限判断的结果。
# frozen=True 让实例不可变，slots=True 减少动态属性，适合作为简单结果对象。
@dataclass(frozen=True, slots=True)
class MCPPermissionDecision:
    # allowed 表示是否允许本次 MCP Tool 调用。
    allowed: bool
    # error_message 保存拒绝原因，允许时为空字符串。
    error_message: str = ""


# 类作用：
# MCPPolicy 封装 MCP 权限判断逻辑。
# BaseMcpClient 会在每次调用工具前使用它检查 agent_name/tool_name 是否在白名单中。
class MCPPolicy:
    # 函数作用：
    # 初始化权限策略。
    #
    # 参数说明：
    # - permissions：可选的自定义权限表；不传时使用 DEFAULT_AGENT_TOOL_PERMISSIONS。
    def __init__(
        self,
        permissions: dict[str, set[str]] | None = None,
        *,
        high_risk_allowlist: set[str] | None = None,
    ) -> None:
        # 保存权限表。注意这里不修改默认表内容，只引用或使用传入表。
        self._permissions = permissions or DEFAULT_AGENT_TOOL_PERMISSIONS
        self._high_risk_allowlist = set(high_risk_allowlist or set())

    # 函数作用：
    # 简化版权限判断，只返回布尔值。
    #
    # 参数说明：
    # - agent_name：发起调用的 Agent 名称。
    # - tool_name：目标 MCP Tool 名称。
    #
    # 返回值：
    # - 允许返回 True，否则 False。
    def is_allowed(self, agent_name: str, tool_name: str) -> bool:
        # 复用 check，避免布尔判断和详细判断两套逻辑不一致。
        return self.check(agent_name, tool_name).allowed

    # 函数作用：
    # 执行完整权限判断，并返回是否允许和拒绝原因。
    #
    # 参数说明：
    # - agent_name：Agent 名称，可能来自类 name 或外部传入。
    # - tool_name：MCP Tool 名称。
    #
    # 返回值：
    # - 返回 MCPPermissionDecision。
    def check(self, agent_name: str, tool_name: str) -> MCPPermissionDecision:
        # 规范化 Agent 名称，例如把 "Filter Agent" 转为 "filter"。
        agent = self._normalize_agent(agent_name)
        # 工具名去除首尾空格，避免配置或调用时多余空白导致误判。
        tool = str(tool_name).strip()
        # 没有 Agent 名称时拒绝，因为无法判断权限边界。
        if not agent:
            return MCPPermissionDecision(False, f"MCP permission denied: missing agent for tool `{tool}`")
        # 查询该 Agent 的允许工具集合。
        allowed_tools = self._permissions.get(agent)
        # 未知 Agent 一律拒绝，防止新 Agent 默认拥有所有权限。
        if allowed_tools is None:
            return MCPPermissionDecision(False, f"MCP permission denied: unknown agent `{agent}`")
        if tool in HIGH_RISK_TOOLS and tool not in self._high_risk_allowlist:
            return MCPPermissionDecision(
                False,
                f"MCP permission denied: high-risk tool `{tool}` is disabled by default",
            )
        # 工具不在白名单中则拒绝，并给出明确错误消息。
        if tool not in allowed_tools:
            return MCPPermissionDecision(
                False,
                f"MCP permission denied: agent `{agent}` cannot call tool `{tool}`",
            )
        # 命中白名单则允许。
        return MCPPermissionDecision(True)

    # 函数作用：
    # 查询某个 Agent 当前允许调用的工具集合。
    #
    # 参数说明：
    # - agent_name：Agent 名称。
    #
    # 返回值：
    # - 返回 set[str]，如果 Agent 未知则返回空集合。
    def allowed_tools(self, agent_name: str) -> set[str]:
        # 返回新 set，避免调用方修改内部权限表。
        return set(self._permissions.get(self._normalize_agent(agent_name), set()))

    # 函数作用：
    # 规范化 Agent 名称，提升权限判断的容错性。
    #
    # 参数说明：
    # - agent_name：原始名称，可能包含大小写、后缀或空格。
    #
    # 返回值：
    # - 返回小写、去后缀后的名称。
    def _normalize_agent(self, agent_name: str) -> str:
        # replace("_agent", "") 和 replace(" agent", "") 让 "filter_agent"、"filter agent" 都匹配 "filter"。
        return str(agent_name or "").strip().lower().replace("_agent", "").replace(" agent", "")
