# 文件作用：
# 本文件实现改写 Agent，负责把文章摘要改写成可保存或发布的中文知识笔记/推文文本。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 Agent 层，是文章处理链路中 SummaryAgent 之后的节点。
#
# 主要内容：
# 1. RewriteAgent 类：读取每篇文章的 summary，调用 LLMTool.rewrite_post 写入 post_text。
#
# 关键调用关系：
# - 被 ArticleWorkflow 的 LangGraph 或顺序流程调用。
# - 调用 app.tools.LLMTool，底层 provider 由配置选择。
# - 输出的 post_text 会被 CheckAgent 校验，并最终由 GoFrame 写入 posts 表或生成 Markdown。
#
# 初学者阅读建议：
# 先确认 SummaryAgent 已经写入 result["summary"]，再看本文件如何把摘要变成最终文本。
from __future__ import annotations

from app.agents.base import BaseAgent
from app.config import Settings
from app.contracts import JsonDict
from app.tools import LLMTool, build_llm_tool


# 类作用：
# RewriteAgent 负责内容改写阶段。
# 它把摘要与原文章信息组合后交给 LLMTool，得到适合输出的 post_text。
class RewriteAgent(BaseAgent):
    # name 用于工作流节点命名，也便于日志中识别当前执行阶段。
    name = "rewrite"

    # 函数作用：
    # 初始化改写 Agent。
    #
    # 参数说明：
    # - skill_text：改写技能提示词，用于约束文风、结构和禁止事项。
    # - llm_tool：LLM 调用工具，通常由 ArticleWorkflow 统一注入。
    #
    # 返回值：
    # - 构造函数不返回值。
    def __init__(self, skill_text: str = "", llm_tool: LLMTool | None = None) -> None:
        # 保存改写技能文本。
        super().__init__(skill_text)
        # 如果没有注入 llm_tool，就使用默认配置创建，便于单独测试本 Agent。
        self.llm_tool = llm_tool or build_llm_tool(Settings())

    # 函数作用：
    # 遍历文章处理结果，把已有摘要改写成 post_text。
    #
    # 参数说明：
    # - state：工作流共享状态，包含 article_results 和每项 result["summary"]。
    #
    # 返回值：
    # - 返回写入 post_text 和 issues 后的 state。
    #
    # 调用关系：
    # - 被 ArticleWorkflow 文章流程调用。
    # - 内部调用 LLMTool.rewrite_post。
    def run(self, state: JsonDict) -> JsonDict:
        # 逐篇处理文章结果。
        for result in state.get("article_results", []):
            # 被 FilterAgent 淘汰的文章不生成推文，防止无关内容进入输出。
            if not result.get("keep"):
                continue
            # 调用 LLMTool，把原文章、摘要和改写技能文本传给 LLM。
            # str(...) 保证 summary 缺失时传入空字符串，而不是 None。
            output = self.llm_tool.rewrite_post(result["article"], str(result.get("summary", "")), self.skill_text)
            # 保存最终改写文本；GoFrame 后端后续会把它写入 posts 表或 Markdown 输出。
            result["post_text"] = output.post_text
            # 记录 LLMTool 生成过程中出现的问题，例如 fallback 或校验失败。
            if output.issues:
                result.setdefault("issues", []).extend(output.issues)
        # 返回更新后的 state，交给 CheckAgent 做最终完整性校验。
        return state
