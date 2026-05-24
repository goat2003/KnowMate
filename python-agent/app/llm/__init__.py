# 文件作用：
# 本文件导出 app.llm 包中的轻量 MockLLM。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 LLM 包入口。
#
# 主要内容：
# 1. 导入 MockLLM。
# 2. 通过 __all__ 声明对外导出名称。
#
# 关键调用关系：
# - 供旧接口、示例或测试从 app.llm import MockLLM 使用。
#
# 初学者阅读建议：
# 当前核心 LLM 调用入口是 app.tools.llm_tool.LLMTool；本包只是保留一个简单 mock 类。
from .mock import MockLLM

# __all__ 控制 from app.llm import * 时导出的名称。
__all__ = ["MockLLM"]
