# 文件作用：
# 本文件是兼容旧导入路径的转发模块。
# 它把 python-agent/app/tools/llm_tool.py 中的公共符号重新导出，避免旧代码 import tools.llm_tool 时失效。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的兼容层，不包含真实 LLM 调用逻辑。
#
# 主要内容：
# 1. 通配导入 app.tools.llm_tool 的全部公开符号。
#
# 关键调用关系：
# - 旧代码或示例可能通过 tools.llm_tool 导入 LLMTool、build_llm_tool 等。
#
# 初学者阅读建议：
# 如果要理解 LLM Provider、JSON repair 和 fallback，请阅读 app/tools/llm_tool.py。
# noqa: F401,F403 表示允许“导入后未直接使用”和“通配导入”，这是兼容转发模块的常见写法。
from app.tools.llm_tool import *  # noqa: F401,F403
