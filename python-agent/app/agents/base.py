# 文件作用：
# 本文件定义所有 Agent 的基础类，统一约定 Agent 必须具备 name 和 run 方法。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 Agent 层，是 FilterAgent、SummaryAgent、RewriteAgent 等具体 Agent 的父类。
#
# 主要内容：
# 1. BaseAgent 类：保存技能提示词，并声明 run 方法接口。
#
# 关键调用关系：
# - 被 app.agents 下的各个具体 Agent 继承。
# - 具体 Agent 实例由 app.workflow.graph.ArticleWorkflow 创建并调度。
#
# 初学者阅读建议：
# 先理解 BaseAgent 只定义统一形状，不实现业务逻辑；
# 真正的文章筛选、总结、改写、校验和记忆更新都在子类的 run 方法中完成。
from __future__ import annotations

from app.contracts import JsonDict


# 类作用：
# BaseAgent 是所有 Agent 的共同父类。
# 它让工作流可以用统一方式调用 agent.run(state)，不需要关心具体 Agent 的内部实现。
class BaseAgent:
    # name 是 Agent 的短名称，会用于 MCP 权限判断和 mcp_call_logs 中的 agent_name 字段。
    name = "base"

    # 函数作用：
    # 初始化 Agent，并保存该 Agent 对应的技能提示词文本。
    #
    # 参数说明：
    # - skill_text：从 app/skills/*.md 读取的提示词或规则文本，供需要 LLM 的 Agent 使用。
    #
    # 返回值：
    # - 构造函数不返回值。
    def __init__(self, skill_text: str = "") -> None:
        # 保存技能文本；子类可以在调用 LLM 时把它拼进 system prompt。
        self.skill_text = skill_text

    # 函数作用：
    # 声明 Agent 执行入口。
    #
    # 参数说明：
    # - state：工作流共享状态，包含文章、反馈、用户画像、MCP 策略等数据。
    #
    # 返回值：
    # - 子类应返回更新后的 state。
    #
    # 调用关系：
    # - 被 ArticleWorkflow 或 LangGraph 调用。
    def run(self, state: JsonDict) -> JsonDict:
        # BaseAgent 不知道具体业务如何处理，因此抛出 NotImplementedError 要求子类实现。
        raise NotImplementedError
