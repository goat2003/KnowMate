# 文件作用：
# 本文件封装 fetch-mcp 的网页抓取和 HTML 处理工具调用。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的 MCP Client 层，主要供 FilterAgent 或未来的校验/摘要流程使用。
#
# 主要内容：
# 1. FetchClient 类：提供 fetch_url、extract_main_content、clean_html、check_url_alive 方法。
#
# 关键调用关系：
# - 继承 BaseMcpClient，权限检查、失败降级和 mcp_call_logs 生成由父类完成。
# - FilterAgent 在文章缺少 raw_text 时可调用 fetch_url 补全文本。
#
# 初学者阅读建议：
# 先看每个方法对应的 MCP Tool 名称，再回到 BaseMcpClient.call_tool 理解统一调用链路。
from __future__ import annotations

from app.mcp.base_client import BaseMcpClient, McpCallResult


# 类作用：
# FetchClient 是 fetch-mcp 的专用客户端。
# 它把网页抓取相关工具包装成 Python 方法，避免 Agent 手写工具名和 payload。
class FetchClient(BaseMcpClient):
    # server_name 用于选择 fetch-mcp endpoint，也会写入 mcp_call_logs.server_name。
    server_name = "fetch-mcp"

    # 函数作用：
    # 调用 fetch_webpage 工具，根据 URL 获取网页内容。
    #
    # 参数说明：
    # - url：待抓取网页地址。
    # - agent_name：发起调用的 Agent 名称。
    # - run_id：本次任务 id。
    #
    # 返回值：
    # - 返回 McpCallResult，result 中通常包含 title、raw_text 等字段。
    def fetch_url(self, url: str, *, agent_name: str, run_id: str) -> McpCallResult:
        # 通过父类 call_tool 统一执行权限判断、标准 MCP 调用和日志生成。
        return self.call_tool("fetch_webpage", {"url": url}, agent_name=agent_name, run_id=run_id)

    # 函数作用：
    # 调用 extract_main_content 工具，从 HTML 中抽取主要正文。
    #
    # 参数说明：
    # - html：原始 HTML 字符串。
    # - agent_name：发起调用的 Agent 名称。
    # - run_id：本次任务 id。
    #
    # 返回值：
    # - 返回 McpCallResult，result 中通常包含 raw_text。
    def extract_main_content(self, html: str, *, agent_name: str, run_id: str) -> McpCallResult:
        # payload 使用 {"html": html}，与 MCP Server 的工具参数协议保持一致。
        return self.call_tool("extract_main_content", {"html": html}, agent_name=agent_name, run_id=run_id)

    # 函数作用：
    # 调用 clean_html 工具，清理 HTML 中的脚本或噪声内容。
    #
    # 参数说明：
    # - html：待清理 HTML。
    # - agent_name：发起调用的 Agent 名称。
    # - run_id：本次任务 id。
    #
    # 返回值：
    # - 返回 McpCallResult，result 中通常包含清理后的 html。
    def clean_html(self, html: str, *, agent_name: str, run_id: str) -> McpCallResult:
        # 实际清洗逻辑在 fetch-mcp server 中，本客户端只负责发起调用。
        return self.call_tool("clean_html", {"html": html}, agent_name=agent_name, run_id=run_id)

    # 函数作用：
    # 调用 check_url_alive 工具，检查 URL 是否可访问。
    #
    # 参数说明：
    # - url：待检查 URL。
    # - agent_name：发起调用的 Agent 名称。
    # - run_id：本次任务 id。
    #
    # 返回值：
    # - 返回 McpCallResult，result 中通常包含 alive 和 status_code。
    def check_url_alive(self, url: str, *, agent_name: str, run_id: str) -> McpCallResult:
        # check_url_alive 可供 CheckAgent 或后续校验流程使用。
        return self.call_tool("check_url_alive", {"url": url}, agent_name=agent_name, run_id=run_id)
