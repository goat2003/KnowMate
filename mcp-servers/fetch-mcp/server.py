# 文件作用：
# 本文件实现 fetch-mcp 服务，负责网页抓取、HTML 清洗、正文抽取和 URL 可用性检查。
# mock 模式下不访问外网，会返回确定性的模拟 HTML；真实模式下使用 urllib 发起 HTTP 请求。
#
# 在项目中的位置：
# 本文件属于 MCP Server 层，被 Python Agent 的 FetchClient 通过 JSON-RPC 调用。
#
# 主要内容：
# 1. CONFIG：读取 mock、代理和超时配置。
# 2. TOOLS：声明 fetch_webpage、extract_main_content、clean_html、check_url_alive。
# 3. handle：根据工具名分发请求。
# 4. _fetch / _check_alive：区分 mock 和真实 HTTP 逻辑。
# 5. _TextExtractor：基于 HTMLParser 抽取文本。
#
# 关键调用关系：
# - Python Agent FilterAgent 可在文章缺少 raw_text 时调用 fetch_webpage。
# - CheckAgent 或后续校验流程可调用 check_url_alive。
#
# 初学者阅读建议：
# 先看 CONFIG["mock_mode"] 如何决定是否访问真实网络，再看 _clean_text 如何把 HTML 转成可读文本。
from __future__ import annotations

from html.parser import HTMLParser
import os
from pathlib import Path
import re
import sys
from urllib import request as urlrequest
from urllib.error import URLError
from urllib.parse import urlparse

# 将公共 MCP 框架加入导入路径。
sys.path.append(str(Path(__file__).resolve().parents[1] / "common"))

from simple_http_mcp import ToolError, ToolSpec, require_str, run_server  # noqa: E402


# CONFIG 会在 /health 返回，也控制 fetch 的 mock/真实行为。
CONFIG = {
    "mock_mode": os.getenv("FETCH_MOCK_MODE", "true").lower() != "false",
    "real_fetch_proxy": os.getenv("REAL_FETCH_PROXY", ""),
    "timeout_seconds": int(os.getenv("FETCH_TIMEOUT_SECONDS", "5")),
}

# TOOLS 声明 fetch-mcp 对外提供的工具及其输入输出结构。
TOOLS = [
    # fetch_webpage 根据 URL 获取网页 HTML 和 raw_text。
    ToolSpec(
        name="fetch_webpage",
        description="Fetch a webpage or return deterministic mock HTML when mock mode is enabled.",
        input_schema={"type": "object", "required": ["url"], "properties": {"url": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"url": {"type": "string"}, "html": {"type": "string"}}},
        examples=[{"request": {"url": "https://example.com"}, "response": {"url": "https://example.com", "status_code": 200}}],
    ),
    # extract_main_content 从 HTML 中提取标题和正文。
    ToolSpec(
        name="extract_main_content",
        description="Extract readable text from raw HTML.",
        input_schema={"type": "object", "required": ["html"], "properties": {"html": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"title": {"type": "string"}, "text": {"type": "string"}}},
        examples=[{"request": {"html": "<h1>Title</h1><p>Body</p>"}, "response": {"title": "Title", "text": "Title Body"}}],
    ),
    # clean_html 去掉脚本、样式和标签，返回纯文本。
    ToolSpec(
        name="clean_html",
        description="Remove scripts, styles, tags, and repeated whitespace from HTML.",
        input_schema={"type": "object", "required": ["html"], "properties": {"html": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"clean_text": {"type": "string"}}},
        examples=[{"request": {"html": "<p>Hello <b>world</b></p>"}, "response": {"clean_text": "Hello world"}}],
    ),
    # check_url_alive 检查 URL 看起来是否可访问。
    ToolSpec(
        name="check_url_alive",
        description="Check whether a URL looks reachable. Mock mode returns true for valid HTTP URLs.",
        input_schema={"type": "object", "required": ["url"], "properties": {"url": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"alive": {"type": "boolean"}, "status_code": {"type": "integer"}}},
        examples=[{"request": {"url": "https://example.com"}, "response": {"alive": True, "status_code": 200}}],
    ),
]


# 函数作用：
# MCP 工具分发入口。
#
# 参数说明：
# - tool：工具名。
# - payload：工具参数。
#
# 返回值：
# - 返回工具输出字典。
def handle(tool: str, payload: dict[str, object]) -> dict[str, object]:
    # fetch_webpage 先校验 URL 格式，再抓取。
    if tool == "fetch_webpage":
        url = _valid_url(require_str(payload, "url"))
        return _fetch(url)
    # extract_main_content 从 HTML 中提取标题和正文文本。
    if tool == "extract_main_content":
        html = require_str(payload, "html")
        text = _clean_text(html)
        return {"title": _extract_title(html), "text": text, "length": len(text), "mock": CONFIG["mock_mode"]}
    # clean_html 只返回清洗后的纯文本。
    if tool == "clean_html":
        html = require_str(payload, "html")
        text = _clean_text(html)
        return {"clean_text": text, "length": len(text)}
    # check_url_alive 检查 URL 是否存活。
    if tool == "check_url_alive":
        url = _valid_url(require_str(payload, "url"))
        return _check_alive(url)
    raise ToolError(f"unknown tool `{tool}`", code=-32601)


# 函数作用：
# 抓取网页或返回 mock HTML。
#
# 参数说明：
# - url：已校验的 http(s) URL。
#
# 返回值：
# - 返回 url、status_code、html、raw_text 和 mock 标记。
def _fetch(url: str) -> dict[str, object]:
    # mock 模式不访问外网，直接构造可预测 HTML。
    if CONFIG["mock_mode"]:
        html = f"<html><head><title>Mock page</title></head><body><main><h1>Mock page</h1><p>Fetched mock content for {url}</p></main></body></html>"
        return {"url": url, "status_code": 200, "html": html, "raw_text": _clean_text(html), "mock": True}
    # 真实模式使用标准库 urllib 请求网页。
    try:
        # User-Agent 标记调用来源，避免某些站点拒绝默认 Python UA。
        req = urlrequest.Request(url, headers={"User-Agent": "knowledge-post-agent-fetch-mcp/0.1"})
        # with 自动关闭响应对象。
        with urlrequest.urlopen(req, timeout=CONFIG["timeout_seconds"]) as response:
            html = response.read().decode("utf-8", errors="replace")
            return {"url": url, "status_code": response.status, "html": html, "raw_text": _clean_text(html), "mock": False}
    except URLError as exc:
        # 抓取失败转换为 ToolError，由 simple_http_mcp 返回 JSON-RPC error。
        raise ToolError("failed to fetch webpage", data={"url": url, "detail": str(exc)}) from exc


# 函数作用：
# 检查 URL 是否可访问。
#
# 参数说明：
# - url：已校验 URL。
#
# 返回值：
# - 返回 alive、status_code 和 mock 标记。
def _check_alive(url: str) -> dict[str, object]:
    # mock 模式下只要 URL 格式合法就认为可访问。
    if CONFIG["mock_mode"]:
        return {"url": url, "alive": True, "status_code": 200, "mock": True}
    # 真实模式使用 HEAD 请求降低流量。
    try:
        req = urlrequest.Request(url, method="HEAD", headers={"User-Agent": "knowledge-post-agent-fetch-mcp/0.1"})
        with urlrequest.urlopen(req, timeout=CONFIG["timeout_seconds"]) as response:
            return {"url": url, "alive": response.status < 400, "status_code": response.status, "mock": False}
    except Exception as exc:
        # URL 不可访问时不抛错，而是返回 alive=False，便于校验流程继续。
        return {"url": url, "alive": False, "status_code": 0, "error": str(exc), "mock": False}


# 函数作用：
# 校验 URL 必须是绝对 http(s) 地址。
def _valid_url(url: str) -> str:
    # urlparse 解析 scheme、host、path 等部分。
    parsed = urlparse(url)
    # 只允许 http/https 且必须有 netloc。
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError("`url` must be an absolute http(s) URL", data={"url": url})
    return url


# 函数作用：
# 从 HTML 中提取标题。
def _extract_title(html: str) -> str:
    # 优先读取 <title>。
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return _clean_text(match.group(1))
    # 没有 title 时尝试读取第一个 h1。
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.IGNORECASE | re.DOTALL)
    return _clean_text(match.group(1)) if match else ""


# 函数作用：
# 将 HTML 清理成纯文本。
def _clean_text(html: str) -> str:
    # 先移除 script/style 内容，避免脚本代码进入正文。
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    # 使用 HTMLParser 收集文本节点。
    parser = _TextExtractor()
    parser.feed(html)
    # 压缩重复空白。
    return " ".join(parser.text.split())


# 类作用：
# _TextExtractor 是简单 HTML 文本抽取器。
# 它继承 HTMLParser，只收集文本节点，不保留标签结构。
class _TextExtractor(HTMLParser):
    # 函数作用：
    # 初始化文本片段列表。
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    # 属性作用：
    # 返回拼接后的文本。
    @property
    def text(self) -> str:
        return " ".join(self.parts)

    # 函数作用：
    # HTMLParser 在遇到文本节点时会调用本方法。
    def handle_data(self, data: str) -> None:
        # 只保留非空白文本片段。
        if data.strip():
            self.parts.append(data.strip())


# 直接运行本文件时启动 fetch-mcp。
if __name__ == "__main__":
    run_server("fetch-mcp", int(os.getenv("PORT", "7002")), TOOLS, handle, CONFIG)
