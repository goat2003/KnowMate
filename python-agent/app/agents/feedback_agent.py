# 文件作用：
# 本文件实现反馈提取 Agent，负责从用户反馈中提取情绪和偏好信号。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 Agent 层，是反馈处理链路的第一个节点。
#
# 主要内容：
# 1. FeedbackAgent 类：调用 LLMTool.extract_feedback，写入 sentiment 和 extracted_feedback。
#
# 关键调用关系：
# - 被 ArticleWorkflow 的反馈 LangGraph 或顺序流程调用。
# - 调用 app.tools.LLMTool，底层可能使用 mock LLM 或真实 OpenAI-compatible API。
# - 输出结果会继续传给 MemoryAgent 更新 user_profile_snapshot。
#
# 初学者阅读建议：
# 先看 ProcessFeedbackRequest 中 feedback 字段，再看本文件如何把原始反馈转换成 MemoryAgent 可用的偏好信号。
from __future__ import annotations

from app.agents.base import BaseAgent
from app.config import Settings
from app.contracts import JsonDict
from app.tools import LLMTool, build_llm_tool


# 类作用：
# FeedbackAgent 负责用户反馈理解。
# 它将评分、文本、反馈类型等输入交给 LLMTool，得到结构化情绪和偏好列表。
class FeedbackAgent(BaseAgent):
    # name 用于工作流节点名和日志标识。
    name = "feedback"

    # 函数作用：
    # 初始化反馈 Agent。
    #
    # 参数说明：
    # - skill_text：反馈提取技能提示词，用于约束 LLM 如何识别偏好。
    # - llm_tool：LLM 调用工具，通常由 ArticleWorkflow 注入。
    #
    # 返回值：
    # - 构造函数不返回值。
    def __init__(self, skill_text: str = "", llm_tool: LLMTool | None = None) -> None:
        # 保存反馈提取技能文本。
        super().__init__(skill_text)
        # 没有传入 llm_tool 时用默认 Settings 创建，便于单元测试独立运行。
        self.llm_tool = llm_tool or build_llm_tool(Settings())

    # 函数作用：
    # 提取本次反馈中的情绪和偏好信号。
    #
    # 参数说明：
    # - state：工作流共享状态，包含 feedback 列表。
    #
    # 返回值：
    # - 返回写入 sentiment、extracted_feedback 和可选 feedback_issues 后的 state。
    #
    # 调用关系：
    # - 被 ArticleWorkflow 反馈流程调用。
    # - 内部调用 LLMTool.extract_feedback。
    def run(self, state: JsonDict) -> JsonDict:
        # list(...) 复制反馈列表，避免 LLMTool 内部处理影响原始 state 引用。
        output = self.llm_tool.extract_feedback(list(state.get("feedback", [])), self.skill_text)
        # sentiment 表示整体反馈情绪，MemoryAgent 会把它写入用户画像快照。
        state["sentiment"] = output.sentiment
        # extracted_feedback 是结构化偏好信号，MemoryAgent 会用它更新画像和记忆。
        state["extracted_feedback"] = output.extracted_feedback
        state["structured_feedback"] = output.structured_feedback
        # 如果 LLM 解析、修复或 fallback 过程中出现问题，就记录在 state 中供排查。
        if output.issues:
            state["feedback_issues"] = output.issues
        # 返回更新后的 state，下一步由 MemoryAgent 处理。
        return state
