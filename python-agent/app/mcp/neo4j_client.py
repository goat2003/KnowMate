# 文件作用：
# 本文件封装 neo4j-mcp 的用户兴趣图谱查询和更新工具调用。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 MCP Client 层，被 FilterAgent 和 MemoryAgent 使用。
#
# 主要内容：
# 1. Neo4jClient 类：提供 get_profile_context、update_profile、get_related_topics、explain_recommendation。
#
# 关键调用关系：
# - 继承 BaseMcpClient，统一复用权限检查、异常降级和日志生成。
# - FilterAgent 读取用户兴趣图谱上下文。
# - MemoryAgent 根据反馈更新用户兴趣图谱。
#
# 初学者阅读建议：
# 先理解 user_profile_snapshot 是关系图谱的输入快照，
# 再看 update_profile 如何把反馈结果提交给 neo4j-mcp。
from __future__ import annotations

from app.contracts import JsonDict
from app.mcp.base_client import BaseMcpClient, McpCallResult


# 类作用：
# Neo4jClient 是 neo4j-mcp 的专用客户端。
# 它把用户画像和兴趣图谱相关的 MCP Tool 包装为 Python 方法。
class Neo4jClient(BaseMcpClient):
    # server_name 用于找到 neo4j-mcp endpoint，并写入 mcp_call_logs。
    server_name = "neo4j-mcp"

    # 函数作用：
    # 查询用户兴趣图谱上下文。
    #
    # 参数说明：
    # - user_id：用户 id，缺失时会使用 default-user。
    # - snapshot：当前 user_profile_snapshot。
    # - agent_name：发起调用的 Agent 名称。
    # - run_id：本次任务 id。
    #
    # 返回值：
    # - 返回 McpCallResult，result 中可能包含 topics 等上下文。
    def get_profile_context(self, user_id: str, snapshot: JsonDict, *, agent_name: str, run_id: str) -> McpCallResult:
        # query_user_interest_graph 是 neo4j-mcp 暴露的查询工具名。
        return self.call_tool(
            "query_user_interest_graph",
            # user_id 缺失时使用 default-user，避免 MCP 工具收到空 id。
            {"user_id": user_id or "default-user", "snapshot": snapshot},
            agent_name=agent_name,
            run_id=run_id,
        )

    # 函数作用：
    # 根据反馈提取结果更新用户兴趣图谱。
    #
    # 参数说明：
    # - snapshot：MemoryAgent 已更新的用户画像快照。
    # - extracted_feedback：从用户反馈中提取出的偏好信号。
    # - sentiment：整体反馈情绪。
    # - agent_name：发起调用的 Agent 名称。
    # - run_id：本次任务 id。
    #
    # 返回值：
    # - 返回 McpCallResult，result 中通常包含 updated 等字段。
    def update_profile(
        self,
        snapshot: JsonDict,
        extracted_feedback: list[str],
        sentiment: str,
        *,
        agent_name: str,
        run_id: str,
    ) -> McpCallResult:
        # update_user_interest_graph 是写图谱工具，只有 memory Agent 默认有权限调用。
        return self.call_tool(
            "update_user_interest_graph",
            {
                "event_id": run_id,
                # user_id 从 snapshot 中读取，缺失时使用 default-user 保证 payload 完整。
                "user_id": str(snapshot.get("user_id", "default-user")),
                # snapshot 是更新后的快照，供 MCP Server 同步到图谱节点属性。
                "snapshot": snapshot,
                # extracted_feedback 表示本次反馈新增的偏好或问题信号。
                "extracted_feedback": extracted_feedback,
                # sentiment 表示本次反馈总体倾向。
                "sentiment": sentiment,
            },
            agent_name=agent_name,
            run_id=run_id,
        )

    # 函数作用：
    # 查询某个主题的相关主题。
    #
    # 参数说明：
    # - topic：主题关键词。
    # - limit：返回数量上限。
    # - agent_name：发起调用的 Agent 名称。
    # - run_id：本次任务 id。
    #
    # 返回值：
    # - 返回 McpCallResult。
    def get_related_topics(self, topic: str, limit: int = 5, *, agent_name: str, run_id: str) -> McpCallResult:
        # get_related_topics 可帮助 Agent 扩展用户兴趣上下文。
        return self.call_tool("get_related_topics", {"topic": topic, "limit": limit}, agent_name=agent_name, run_id=run_id)

    # 函数作用：
    # 解释某篇文章为什么被推荐给用户。
    #
    # 参数说明：
    # - user_id：用户 id。
    # - article：文章字典。
    # - agent_name：发起调用的 Agent 名称。
    # - run_id：本次任务 id。
    #
    # 返回值：
    # - 返回 McpCallResult。
    def explain_recommendation(self, user_id: str, article: JsonDict, *, agent_name: str, run_id: str) -> McpCallResult:
        # 当前默认权限表未给 filter Agent 开放 explain_recommendation，因此调用会被权限策略拒绝。
        return self.call_tool(
            "explain_recommendation",
            {"user_id": user_id or "default-user", "article": article},
            agent_name=agent_name,
            run_id=run_id,
        )
