# fetch-mcp 中文说明

> 原文镜像：`mcp-servers/fetch-mcp/README.md`

基于官方 SDK 的 MCP server，用于网页抓取和 HTML 清理。

## 启动

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\mcp-servers\fetch-mcp
$env:MCP_TRANSPORT="streamable_http"
python server.py
```

默认端口：`7002`。

配置字段：

- `PORT`：HTTP 端口，默认 `7002`。
- `FETCH_MOCK_MODE`：默认 `true`。
- `FETCH_TIMEOUT_SECONDS`：默认 `5`。
- `REAL_FETCH_PROXY`：预留给未来 crawler/proxy 服务。

## Tools

### fetch_webpage

请求参数：

```json
{"url": "https://example.com"}
```

响应输出：

```json
{"url": "https://example.com", "status_code": 200, "html": "<html>...</html>", "raw_text": "Mock page ...", "mock": true}
```

### extract_main_content

请求参数：

```json
{"html": "<html><title>T</title><body><p>Hello</p></body></html>"}
```

响应输出：

```json
{"title": "T", "text": "T Hello", "length": 7, "mock": true}
```

### clean_html

请求参数：

```json
{"html": "<p>Hello <b>world</b></p>"}
```

响应输出：

```json
{"clean_text": "Hello world", "length": 11}
```

### check_url_alive

请求参数：

```json
{"url": "https://example.com"}
```

响应输出：

```json
{"url": "https://example.com", "alive": true, "status_code": 200, "mock": true}
```
