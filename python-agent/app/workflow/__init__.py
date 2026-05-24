# 文件作用：
# 本文件集中导出工作流层的核心 ArticleWorkflow。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 workflow 包入口。
#
# 主要内容：
# 1. 导入 ArticleWorkflow。
# 2. 通过 __all__ 声明对外导出名称。
#
# 关键调用关系：
# - 被 app.grpc_server 通过 from app.workflow import ArticleWorkflow 使用。
#
# 初学者阅读建议：
# 真正的工作流构建和执行逻辑在 graph.py。
from .graph import ArticleWorkflow

# __all__ 控制 from app.workflow import * 时导出的名称。
__all__ = ["ArticleWorkflow"]
