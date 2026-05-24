# 文件作用：
# 本文件实现记忆更新 Agent，负责把用户反馈提取结果写回用户画像快照，并可同步到 MCP 记忆服务。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 Agent 层，是反馈处理链路中 FeedbackAgent 之后的节点。
#
# 主要内容：
# 1. MemoryAgent 类：读取 extracted_feedback 和 sentiment，更新 updated_profile_snapshot。
# 2. run 方法：按 MCP 策略调用 embedding-mcp 和 neo4j-mcp，并生成 mcp_call_logs。
#
# 关键调用关系：
# - 被 ArticleWorkflow 的反馈 LangGraph 或顺序流程调用。
# - 可调用 EmbeddingClient 和 Neo4jClient。
# - 输出 updated_profile_snapshot 后，由 GoFrame 写入 user_profile_snapshot 表。
#
# 初学者阅读建议：
# 先看 FeedbackAgent 如何生成 extracted_feedback，
# 再看本文件如何把这些反馈落到 user_profile_snapshot 和 MCP 调用日志中。
from __future__ import annotations

from app.agents.base import BaseAgent
from app.contracts import JsonDict
from app.mcp.embedding_client import EmbeddingClient
from app.mcp.neo4j_client import Neo4jClient


# 类作用：
# MemoryAgent 负责“长期记忆”更新。
# 在当前 MVP 中，它直接更新字典形式的 user_profile_snapshot，并可通过 MCP 写入向量或图谱记忆。
class MemoryAgent(BaseAgent):
    # name 会被 MCPPolicy 用来判断 memory Agent 是否有权调用 embedding 或 neo4j 工具。
    name = "memory"

    # 函数作用：
    # 初始化记忆 Agent 及其可选 MCP Client。
    #
    # 参数说明：
    # - skill_text：记忆更新技能文本，当前逻辑主要是规则更新，保留该字段便于未来扩展。
    # - embedding_client：用于把反馈文本转换为向量，便于后续语义记忆检索。
    # - neo4j_client：用于把用户兴趣变化同步到图谱记忆。
    #
    # 返回值：
    # - 构造函数不返回值。
    def __init__(
        self,
        skill_text: str = "",
        embedding_client: EmbeddingClient | None = None,
        neo4j_client: Neo4jClient | None = None,
    ) -> None:
        # 调用 BaseAgent 保存 skill_text。
        super().__init__(skill_text)
        # 保存可选 MCP Client；测试或 mock 场景可以不传真实 Client。
        self.embedding_client = embedding_client
        self.neo4j_client = neo4j_client

    # 函数作用：
    # 根据用户反馈更新画像快照，并按策略调用 MCP 记忆工具。
    #
    # 参数说明：
    # - state：反馈流程共享状态，包含 run_id、user_profile_snapshot、extracted_feedback、sentiment、mcp_policy。
    #
    # 返回值：
    # - 返回写入 updated_profile_snapshot 和 mcp_call_logs 后的 state。
    #
    # 调用关系：
    # - 被 ArticleWorkflow 反馈流程调用。
    # - 内部可能调用 embedding-mcp 和 neo4j-mcp。
    def run(self, state: JsonDict) -> JsonDict:
        # run_id 用于标识本次反馈处理任务，并写入 MCP 调用日志。
        run_id = str(state.get("run_id", ""))
        # 复制当前用户画像快照；MemoryAgent 会在副本上更新字段，而不是直接修改原始对象引用。
        snapshot = dict(state.get("user_profile_snapshot", {}))
        # extracted_feedback 来自 FeedbackAgent，表示可以沉淀进用户画像的偏好信号。
        extracted = list(state.get("extracted_feedback", []))
        # sentiment 表示整体反馈情绪，默认 neutral，避免字段缺失导致异常。
        sentiment = str(state.get("sentiment", "neutral"))
        # setdefault 确保 mcp_call_logs 字段存在；如果已有日志则继续追加。
        logs = state.setdefault("mcp_call_logs", [])

        # 如果策略允许 embedding 且 client 存在，就把反馈文本嵌入为向量。
        # 这一步的结果当前只记录日志，未来可以扩展为写入 Milvus 记忆库。
        if self.embedding_client and state.get("mcp_policy", {}).get("enable_embedding"):
            embedded = self.embedding_client.embed_text(
                # 多条反馈用空格拼接成一个文本，作为本次画像更新的语义摘要。
                " ".join(extracted),
                # metadata 标记向量来源，方便 MCP Server 或后续日志排查。
                {"source": "feedback"},
                agent_name=self.name,
                run_id=run_id,
            )
            # 记录 embedding-mcp 调用日志，GoFrame 可写入 mcp_call_logs 表。
            logs.append(embedded.log)

        # 将最新情绪写入用户画像快照，GoFrame 持久化后下次筛选文章可读取。
        snapshot["last_feedback_sentiment"] = sentiment
        # feedback_count 使用字符串保存，兼容 protobuf map<string,string> 和数据库快照字段。
        # int(...) 做数值累加，外层 str(...) 再转回快照中的字符串格式。
        snapshot["feedback_count"] = str(int(snapshot.get("feedback_count", "0") or 0) + len(extracted))
        # 如果本次提取到了反馈，就保留最近三条作为画像中的轻量上下文。
        if extracted:
            snapshot["latest_feedback"] = " | ".join(extracted[-3:])

        # 如果策略允许 neo4j，就把更新后的画像和偏好信号同步到图谱记忆。
        if self.neo4j_client and state.get("mcp_policy", {}).get("enable_neo4j"):
            updated = self.neo4j_client.update_profile(snapshot, extracted, sentiment, agent_name=self.name, run_id=run_id)
            # 记录 neo4j-mcp 调用日志，包含请求、响应、状态和耗时。
            logs.append(updated.log)

        # 写入最终用户画像快照；gRPC 响应会把这个字段返回给 GoFrame。
        state["updated_profile_snapshot"] = snapshot
        return state
