from __future__ import annotations

from html.parser import HTMLParser
import os
from pathlib import Path
import re
import sys
from urllib import request as urlrequest
from urllib.error import URLError
from urllib.parse import urlparse

sys.path.append(str(Path(__file__).resolve().parents[1] / "common"))

from simple_http_mcp import ToolError, ToolSpec, require_str, run_server  # noqa: E402


CONFIG = {
    "mock_mode": os.getenv("FETCH_MOCK_MODE", "true").lower() != "false",
    "real_fetch_proxy": os.getenv("REAL_FETCH_PROXY", ""),
    "timeout_seconds": int(os.getenv("FETCH_TIMEOUT_SECONDS", "5")),
}

TOOLS = [
    ToolSpec(
        name="fetch_webpage",
        description="Fetch a webpage or return deterministic mock HTML when mock mode is enabled.",
        input_schema={"type": "object", "required": ["url"], "properties": {"url": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"url": {"type": "string"}, "html": {"type": "string"}}},
        examples=[{"request": {"url": "https://example.com"}, "response": {"url": "https://example.com", "status_code": 200}}],
    ),
    ToolSpec(
        name="extract_main_content",
        description="Extract readable text from raw HTML.",
        input_schema={"type": "object", "required": ["html"], "properties": {"html": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"title": {"type": "string"}, "text": {"type": "string"}}},
        examples=[{"request": {"html": "<h1>Title</h1><p>Body</p>"}, "response": {"title": "Title", "text": "Title Body"}}],
    ),
    ToolSpec(
        name="clean_html",
        description="Remove scripts, styles, tags, and repeated whitespace from HTML.",
        input_schema={"type": "object", "required": ["html"], "properties": {"html": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"clean_text": {"type": "string"}}},
        examples=[{"request": {"html": "<p>Hello <b>world</b></p>"}, "response": {"clean_text": "Hello world"}}],
    ),
    ToolSpec(
        name="check_url_alive",
        description="Check whether a URL looks reachable. Mock mode returns true for valid HTTP URLs.",
        input_schema={"type": "object", "required": ["url"], "properties": {"url": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"alive": {"type": "boolean"}, "status_code": {"type": "integer"}}},
        examples=[{"request": {"url": "https://example.com"}, "response": {"alive": True, "status_code": 200}}],
    ),
]


def handle(tool: str, payload: dict[str, object]) -> dict[str, object]:
    if tool == "fetch_webpage":
        url = _valid_url(require_str(payload, "url"))
        return _fetch(url)
    if tool == "extract_main_content":
        html = require_str(payload, "html")
        text = _clean_text(html)
        return {"title": _extract_title(html), "text": text, "length": len(text), "mock": CONFIG["mock_mode"]}
    if tool == "clean_html":
        html = require_str(payload, "html")
        text = _clean_text(html)
        return {"clean_text": text, "length": len(text)}
    if tool == "check_url_alive":
        url = _valid_url(require_str(payload, "url"))
        return _check_alive(url)
    raise ToolError(f"unknown tool `{tool}`", code=-32601)


def _fetch(url: str) -> dict[str, object]:
    if CONFIG["mock_mode"]:
        html = f"<html><head><title>Mock page</title></head><body><main><h1>Mock page</h1><p>Fetched mock content for {url}</p></main></body></html>"
        return {"url": url, "status_code": 200, "html": html, "raw_text": _clean_text(html), "mock": True}
    try:
        req = urlrequest.Request(url, headers={"User-Agent": "knowledge-post-agent-fetch-mcp/0.1"})
        with urlrequest.urlopen(req, timeout=CONFIG["timeout_seconds"]) as response:
            html = response.read().decode("utf-8", errors="replace")
            return {"url": url, "status_code": response.status, "html": html, "raw_text": _clean_text(html), "mock": False}
    except URLError as exc:
        raise ToolError("failed to fetch webpage", data={"url": url, "detail": str(exc)}) from exc


def _check_alive(url: str) -> dict[str, object]:
    if CONFIG["mock_mode"]:
        return {"url": url, "alive": True, "status_code": 200, "mock": True}
    try:
        req = urlrequest.Request(url, method="HEAD", headers={"User-Agent": "knowledge-post-agent-fetch-mcp/0.1"})
        with urlrequest.urlopen(req, timeout=CONFIG["timeout_seconds"]) as response:
            return {"url": url, "alive": response.status < 400, "status_code": response.status, "mock": False}
    except Exception as exc:
        return {"url": url, "alive": False, "status_code": 0, "error": str(exc), "mock": False}


def _valid_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError("`url` must be an absolute http(s) URL", data={"url": url})
    return url


def _extract_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return _clean_text(match.group(1))
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.IGNORECASE | re.DOTALL)
    return _clean_text(match.group(1)) if match else ""


def _clean_text(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    parser = _TextExtractor()
    parser.feed(html)
    return " ".join(parser.text.split())


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    @property
    def text(self) -> str:
        return " ".join(self.parts)

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


if __name__ == "__main__":
    run_server("fetch-mcp", int(os.getenv("PORT", "7002")), TOOLS, handle, CONFIG)
