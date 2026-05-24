# 文件作用：
# 本文件集中导出 Agent 层的具体 Agent 类，方便其他模块用 from app.agents import XxxAgent 的方式统一导入。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 Agent 包入口。
#
# 主要内容：
# 1. 导入 CheckAgent、FeedbackAgent、FilterAgent、MemoryAgent、RewriteAgent、SummaryAgent。
# 2. 通过 __all__ 声明该包对外暴露的名称。
#
# 关键调用关系：
# - 被 app.workflow.graph 引用，用于一次性导入所有核心 Agent。
#
# 初学者阅读建议：
# 这里没有业务逻辑，只是包导出文件；真正逻辑请阅读各个 *_agent.py 文件。
from .check_agent import CheckAgent
from .feedback_agent import FeedbackAgent
from .filter_agent import FilterAgent
from .memory_agent import MemoryAgent
from .rewrite_agent import RewriteAgent
from .summary_agent import SummaryAgent

# __all__ 告诉读者和工具“from app.agents import *”时应该导出哪些名称。
# 这样 ArticleWorkflow 可以从一个包入口导入所有 Agent，而不必写多个具体文件路径。
__all__ = [
    "CheckAgent",
    "FeedbackAgent",
    "FilterAgent",
    "MemoryAgent",
    "RewriteAgent",
    "SummaryAgent",
]
