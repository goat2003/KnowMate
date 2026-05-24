# 文件作用：
# 本文件是兼容旧 tools 包导入路径的入口。
# 它把 app.tools.llm_tool 的公共符号重新导出，避免旧代码从 tools 导入 LLM 工具时失败。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的兼容层。
#
# 主要内容：
# 1. 通配导入 app.tools.llm_tool。
#
# 关键调用关系：
# - 示例或旧测试可能使用 from tools import build_llm_tool 等导入方式。
#
# 初学者阅读建议：
# 这里没有真实业务逻辑；核心 LLM 工具请阅读 app/tools/llm_tool.py。
# noqa: F401,F403 允许转发模块使用通配导入。
from app.tools.llm_tool import *  # noqa: F401,F403
