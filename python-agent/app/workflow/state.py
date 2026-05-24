# 文件作用：
# 本文件定义 Python Agent 工作流在各节点之间传递的共享状态结构。
# ArticleWorkflow、LangGraph 节点和顺序兜底流程都会读写这些字段。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的工作流层，是 Agent 之间约定数据流转格式的地方。
#
# 主要内容：
# 1. AgentState：TypedDict 类型，描述文章流程和反馈流程可能出现的 state 字段。
#
# 关键调用关系：
# - 被 app.workflow.graph.ArticleWorkflow 创建 StateGraph 时引用。
# - 被各个 Agent 的 run 方法通过普通 dict 形式读写。
#
# 初学者阅读建议：
# 先把这里的字段和 ProcessArticles / ProcessFeedback 的请求响应对应起来，
# 再去看 FilterAgent、SummaryAgent、MemoryAgent 如何逐步补充这些字段。
from __future__ import annotations

from typing import Any, TypedDict


# 类作用：
# AgentState 是 LangGraph 使用的状态类型说明。
# TypedDict 不会在运行时强制校验字段，而是给 IDE、类型检查器和读代码的人一个结构参考。
#
# 字段说明：
# - run_id：一次任务的唯一标识，用于串联 run_logs、posts、mcp_call_logs 等记录。
# - articles：GoFrame 传入的文章列表，FilterAgent 会先读取它。
# - feedback：GoFrame 传入的用户反馈列表，FeedbackAgent 会先读取它。
# - user_profile_snapshot：用户画像快照，FilterAgent 读取，MemoryAgent 更新。
# - mcp_policy：本次请求允许启用哪些 MCP 能力，例如 embedding、milvus、neo4j。
# - article_results：文章处理的中间和最终结果列表，由多个 Agent 逐步填充。
# - sentiment / extracted_feedback：反馈提取结果，供 MemoryAgent 更新画像。
# - updated_profile_snapshot：反馈流程输出的新用户画像快照。
# - mcp_call_logs：MCP 工具调用日志，最后由 GoFrame 写入 mcp_call_logs 表。
class AgentState(TypedDict, total=False):
    # run_id 是任务追踪字段；total=False 表示这个字段在某些阶段可以暂时不存在。
    run_id: str
    # articles 保存标准化后的文章字典列表，每篇文章至少应包含 article_id、title、url、raw_text 等键。
    articles: list[dict[str, Any]]
    # feedback 保存用户反馈字典列表，每条反馈通常来自 feedback_logs 或 gRPC 请求。
    feedback: list[dict[str, Any]]
    # user_profile_snapshot 保存当前用户画像，值用 str 简化跨语言 gRPC map<string,string> 传输。
    user_profile_snapshot: dict[str, str]
    # mcp_policy 保存 MCP 开关配置，用于控制是否调用外部工具。
    mcp_policy: dict[str, Any]
    # article_results 是文章工作流的主输出，FilterAgent 创建，后续 Agent 继续追加 summary、post_text、issues。
    article_results: list[dict[str, Any]]
    # sentiment 是 FeedbackAgent 判断出的用户反馈整体情绪。
    sentiment: str
    # extracted_feedback 是 FeedbackAgent 从反馈文本中提取出的偏好信号。
    extracted_feedback: list[str]
    # updated_profile_snapshot 是 MemoryAgent 基于反馈生成的新用户画像快照。
    updated_profile_snapshot: dict[str, str]
    # mcp_call_logs 记录 MCP 调用明细，便于 GoFrame 持久化到数据库中排查工具行为。
    mcp_call_logs: list[dict[str, Any]]
