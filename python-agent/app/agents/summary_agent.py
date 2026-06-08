# 文件作用：
# 本文件实现摘要 Agent，负责把通过筛选的文章交给 LLM 生成中文摘要。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 Agent 层，是文章处理链路中 FilterAgent 之后的节点。
#
# 主要内容：
# 1. SummaryAgent 类：读取 article_results，调用 LLMTool.summarize 写入 summary。
#
# 关键调用关系：
# - 被 ArticleWorkflow 的 LangGraph 或顺序流程调用。
# - 调用 app.tools.LLMTool，底层可能使用 mock LLM 或 OpenAI-compatible API。
# - 输出结果会继续传给 RewriteAgent。
#
# 初学者阅读建议：
# 先看 FilterAgent 如何设置 keep，再看本文件如何只处理 keep=True 的文章。
from __future__ import annotations

from app.agents.base import BaseAgent
from app.contracts import JsonDict
from app.tools import LLMTool, build_llm_tool
from app.config import Settings
from app.mcp.fetch_client import FetchClient


# 类作用：
# SummaryAgent 负责文章总结阶段。
# 它不直接访问 gRPC 或数据库，只读取工作流 state，并通过 LLMTool 得到结构化摘要结果。
class SummaryAgent(BaseAgent):
    # name 用于流程标识；当前类不直接调用 MCP，但仍保持统一 Agent 命名。
    name = "summary"

    # 函数作用：
    # 初始化摘要 Agent。
    #
    # 参数说明：
    # - skill_text：摘要技能提示词，用来约束 LLM 输出风格和内容。
    # - llm_tool：可注入的 LLMTool；如果未传入，就根据默认 Settings 创建一个。
    #
    # 返回值：
    # - 构造函数不返回值。
    def __init__(
        self,
        skill_text: str = "",
        llm_tool: LLMTool | None = None,
        fetch_client: FetchClient | None = None,
    ) -> None:
        # 调用父类保存 skill_text。
        super().__init__(skill_text)
        # 复用 ArticleWorkflow 注入的 llm_tool，避免每个 Agent 重复读取配置。
        # 兜底创建 Settings() 主要方便单元测试直接实例化 SummaryAgent。
        self.llm_tool = llm_tool or build_llm_tool(Settings())
        self.fetch_client = fetch_client

    # 函数作用：
    # 遍历筛选结果，对保留下来的文章生成摘要。
    #
    # 参数说明：
    # - state：工作流共享状态，必须已经包含 FilterAgent 写入的 article_results。
    #
    # 返回值：
    # - 返回写入 summary 和 issues 后的 state。
    #
    # 调用关系：
    # - 被 ArticleWorkflow 文章流程调用。
    # - 内部调用 LLMTool.summarize。
    def run(self, state: JsonDict) -> JsonDict:
        # dict(...) 复制用户画像快照，作为 LLM 生成摘要时的上下文，不修改原始 state 字段。
        profile = dict(state.get("user_profile_snapshot", {}))
        policy = dict(state.get("mcp_policy", {}))
        run_id = str(state.get("run_id", ""))
        # 逐篇处理 FilterAgent 生成的结果项。
        for result in state.get("article_results", []):
            # keep=False 的文章已经被过滤，不进入摘要流程，避免浪费 LLM 调用。
            if not result.get("keep"):
                continue
            article = result["article"]
            if (
                policy.get("enable_fetch")
                and not article.get("raw_text")
                and article.get("url")
                and self.fetch_client
            ):
                fetched = self.fetch_client.fetch_url(article["url"], agent_name=self.name, run_id=run_id)
                result.setdefault("mcp_call_logs", []).append(fetched.log)
                if fetched.log.get("success"):
                    article["raw_text"] = str(fetched.result.get("raw_text") or fetched.result.get("text") or "")
                else:
                    result.setdefault("issues", []).append("summary_fetch_failed")
            # 调用 LLMTool 生成结构化摘要。
            # result["article"] 是原文数据，profile 是用户画像，skill_text 是摘要规则。
            output = self.llm_tool.summarize(article, profile, self.skill_text)
            # 将 Pydantic 模型中的 summary 写回 result，供 RewriteAgent 使用。
            result["summary"] = output.summary
            # 如果 LLMTool 发生 repair 或 fallback，会把问题记录到 issues 中，便于后续排查。
            if output.issues:
                result.setdefault("issues", []).extend(output.issues)
        # 返回同一个 state，使后续 Agent 可以继续读取 article_results。
        return state
