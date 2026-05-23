# fetch-mcp

Minimal JSON-RPC style MCP mock server for webpage fetching and HTML cleanup.

## Start

```powershell
cd D:\projects\KnowMate\knowledge-post-agent\mcp-servers\fetch-mcp
python server.py
```

Default port: `7002`.

Config fields:

- `PORT`: HTTP port, default `7002`
- `FETCH_MOCK_MODE`: default `true`
- `FETCH_TIMEOUT_SECONDS`: default `5`
- `REAL_FETCH_PROXY`: reserved for future crawler/proxy service

## Tools

### fetch_webpage

Request arguments:

```json
{"url": "https://example.com"}
```

Response output:

```json
{"url": "https://example.com", "status_code": 200, "html": "<html>...</html>", "raw_text": "Mock page ...", "mock": true}
```

### extract_main_content

Request arguments:

```json
{"html": "<html><title>T</title><body><p>Hello</p></body></html>"}
```

Response output:

```json
{"title": "T", "text": "T Hello", "length": 7, "mock": true}
```

### clean_html

Request arguments:

```json
{"html": "<p>Hello <b>world</b></p>"}
```

Response output:

```json
{"clean_text": "Hello world", "length": 11}
```

### check_url_alive

Request arguments:

```json
{"url": "https://example.com"}
```

Response output:

```json
{"url": "https://example.com", "alive": true, "status_code": 200, "mock": true}
```
