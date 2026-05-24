# 文件作用：
# 本文件提供一个早期/轻量的 MockLLM 类，用于不依赖外部模型生成摘要和推文草稿。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 LLM 辅助层。
# 当前核心 Agent 流程主要使用 app.tools.llm_tool.MockLLMClient，本文件保留给旧接口或简单示例使用。
#
# 主要内容：
# 1. MockLLM.summarize：根据标题和内容生成简单摘要。
# 2. MockLLM.rewrite_as_post：把摘要包装成 Markdown 风格草稿。
#
# 关键调用关系：
# - 通过 app.llm.__init__ 导出。
# - 当前主工作流不直接调用该类。
#
# 初学者阅读建议：
# 不要把 MockLLM 当成真实 LLM 服务；它只是本地规则拼接，核心结构化 LLM 逻辑请看 app/tools/llm_tool.py。
from __future__ import annotations

from app.contracts import JsonDict


# 类作用：
# MockLLM 是简单的本地模拟模型。
# 它不访问网络，也不读取 API Key，只根据输入字段拼接可预测文本。
class MockLLM:
    # 函数作用：
    # 根据文章标题和内容生成短摘要。
    #
    # 参数说明：
    # - article：文章字典，通常包含 title 和 content。
    #
    # 返回值：
    # - 返回字符串摘要。
    def summarize(self, article: JsonDict) -> str:
        # 标题缺失时使用 Untitled，避免输出以空标题开头。
        title = article.get("title") or "Untitled"
        # content 去除首尾空白并把换行替换为空格，使摘要在单行中更稳定。
        content = (article.get("content") or "").strip().replace("\n", " ")
        # 只截取前 160 个字符，避免 mock 摘要过长。
        snippet = content[:160] if content else "No content was provided."
        # 返回 “标题: 片段” 格式。
        return f"{title}: {snippet}"

    # 函数作用：
    # 把标题和摘要包装成 Markdown 风格文章草稿。
    #
    # 参数说明：
    # - title：文章标题。
    # - summary：摘要内容。
    #
    # 返回值：
    # - 返回 Markdown 字符串。
    def rewrite_as_post(self, title: str, summary: str) -> str:
        # 使用固定模板生成草稿，方便本地测试，不代表真实改写模型效果。
        return "\n".join(
            [
                f"# {title}",
                "",
                "## Summary",
                "",
                summary,
                "",
                "## Why it matters",
                "",
                "This mock draft highlights the core idea and leaves room for a real rewrite model.",
            ]
        )
