# 文件作用：
# 本文件集中导出 app.tools 包中的 LLM 工具和结构化输出模型。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的工具包入口。
#
# 主要内容：
# 1. 导出 LLMClient、LLMTool、MockLLMClient、OpenAICompatibleLLMClient、ClaudeLLMClient。
# 2. 导出 SummaryLLMOutput、RewriteLLMOutput、FeedbackLLMOutput。
# 3. 导出 build_llm_tool。
#
# 关键调用关系：
# - 被 SummaryAgent、RewriteAgent、FeedbackAgent 使用。
#
# 初学者阅读建议：
# 这里没有业务逻辑；LLM provider 选择和结构化输出校验在 llm_tool.py。
from .llm_tool import (
    ClaudeLLMClient,
    FeedbackLLMOutput,
    LLMClient,
    LLMTool,
    MockLLMClient,
    OpenAICompatibleLLMClient,
    RewriteLLMOutput,
    SummaryLLMOutput,
    build_llm_tool,
)

# __all__ 声明包对外公开的符号，方便 Agent 从 app.tools 统一导入。
__all__ = [
    "ClaudeLLMClient",
    "FeedbackLLMOutput",
    "LLMClient",
    "LLMTool",
    "MockLLMClient",
    "OpenAICompatibleLLMClient",
    "RewriteLLMOutput",
    "SummaryLLMOutput",
    "build_llm_tool",
]
