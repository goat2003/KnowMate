# 文件作用：
# 本文件实现校验 Agent，负责在文章处理流程末尾检查摘要、推文和原文链接是否完整。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 Agent 层，是文章处理链路的最后一个节点。
#
# 主要内容：
# 1. CheckAgent 类：遍历 article_results，写入 check_pass 和 issues。
#
# 关键调用关系：
# - 被 ArticleWorkflow 的 LangGraph 或顺序流程调用。
# - 读取 SummaryAgent 和 RewriteAgent 写入的 summary、post_text。
# - 输出结果会由 app.grpc_server 转成 ArticleProcessResult protobuf。
#
# 初学者阅读建议：
# 先理解 issues 是跨 Agent 累积的问题列表，再看 check_pass 如何根据 issues 是否为空得到。
from __future__ import annotations

from app.agents.base import BaseAgent
from app.contracts import JsonDict


# 类作用：
# CheckAgent 做轻量、确定性的结果校验。
# 它不调用 LLM，也不调用 MCP，主要负责给 GoFrame 一个明确的成功/失败标记。
class CheckAgent(BaseAgent):
    # name 对应工作流中的 check 节点名称。
    name = "check"

    # 函数作用：
    # 校验每篇文章处理结果是否满足最基本的输出要求。
    #
    # 参数说明：
    # - state：工作流共享状态，必须包含 article_results。
    #
    # 返回值：
    # - 返回写入 check_pass 和 issues 后的 state。
    #
    # 调用关系：
    # - 被 ArticleWorkflow 文章流程调用。
    def run(self, state: JsonDict) -> JsonDict:
        # 遍历每篇文章的处理结果。
        for result in state.get("article_results", []):
            # 复制已有 issues，避免直接复用可能不是 list 的对象，也便于追加新问题。
            issues = list(result.get("issues", []))
            # article 保存原文章字段，URL 校验需要从这里读取。
            article = result.get("article", {})
            # 未通过 FilterAgent 的文章不应该被认为处理成功。
            if not result.get("keep"):
                result["check_pass"] = False
                result["issues"] = issues
                continue
            # 摘要缺失说明 SummaryAgent 没有成功产出可用内容。
            if not result.get("summary"):
                issues.append("missing_summary")
            # 推文缺失说明 RewriteAgent 没有成功产出最终文本。
            if not result.get("post_text"):
                issues.append("missing_post_text")
            # URL 缺失会影响用户回看原文，也会影响后端生成可追溯的 Markdown。
            if not article.get("url"):
                issues.append("missing_url")
            # 写回完整问题列表。
            result["issues"] = issues
            # 没有任何问题时才认为校验通过。
            result["check_pass"] = len(issues) == 0
        # 返回 state，最终由 ArticleWorkflow 整理为 gRPC 响应。
        return state
