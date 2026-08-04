# MCP Tool Usage Skill 中文说明

> 原文镜像：`python-agent/app/skills/mcp_tool_usage_skill.md`

## 任务目标

本 Skill 规定所有 Agent 如何安全调用 MCP Tool。核心原则是：先做权限检查，再调用工具；所有结果必须可追踪；失败可降级；禁止编造 MCP 结果。

## 输入格式

```json
{
  "run_id": "articles-20260523",
  "agent_name": "filter",
  "server_name": "embedding-mcp",
  "tool_name": "embed_text",
  "request_json": {
    "text": "article title and raw text",
    "metadata": {"article_id": "a1"}
  }
}
```

## 输出格式

```json
{
  "result": {
    "embedding": [0.1, 0.2, 0.3],
    "dim": 3
  },
  "log": {
    "run_id": "articles-20260523",
    "agent_name": "filter",
    "server_name": "embedding-mcp",
    "tool_name": "embed_text",
    "request_json": "{\"jsonrpc\":\"2.0\"}",
    "response_json": "{\"jsonrpc\":\"2.0\"}",
    "status": "success",
    "error_message": "",
    "success": true,
    "latency_ms": 12
  }
}
```

## 约束条件

- 每次调用前必须通过 `MCPPolicy` 检查 `agent_name + tool_name`。
- 未授权调用必须直接拒绝，不能发到 MCP Server。
- 所有调用都必须记录日志，包括成功、失败和拒绝。
- MCP 返回值只能作为辅助证据；不能把失败、空结果或 mock 结果当作真实事实。
- 不允许为了让流程通过而伪造工具输出。
- 请求和响应必须保留 JSON 字符串，方便 GoFrame 写入 MySQL。

## 可调用 MCP Tool

按 Agent 权限矩阵调用：

- Filter Agent：`embed_text`、`embed_batch`、`search_similar_memory`、`query_user_interest_graph`、`get_related_topics`
- Summary Agent：`fetch_webpage`、`extract_main_content`、`search_articles`
- Check Agent：`fetch_webpage`、`check_url_alive`、`search_similar_memory`、`semantic_deduplicate`
- Feedback Agent：`embed_text`、`search_similar_memory`
- Memory Agent：`embed_text`、`insert_memory_vector`、`search_similar_memory`、`update_user_interest_graph`、`query_user_interest_graph`、`get_related_topics`
- Output Agent：`save_markdown`、`generate_daily_report`、`generate_weekly_report`、`send_email`

## 禁止调用 MCP Tool

- 任何不在当前 Agent allowlist 中的工具。
- 任何没有明确 `run_id` 和 `agent_name` 的工具调用。
- 任何会造成外部副作用但没有在 MVP 中实现权限和审计的工具。

## 失败处理

- 权限拒绝：返回 `status=denied`、`success=false`、`error.code=MCP_PERMISSION_DENIED`。
- MCP Server 超时或返回错误：返回 `status=failed`、`success=false`、`error.code=MCP_CALL_FAILED`。
- 调用失败后 Agent 应尽量用本地规则继续处理，并在自身 `issues` 中记录降级原因。
- 如果 MCP 结果缺字段，按失败处理，不要推断缺失字段。
- GoFrame 接收 `mcp_call_logs` 后必须写入 MySQL `mcp_call_logs`。

## 示例

Filter Agent 尝试调用禁止的 `fetch_webpage`：

```json
{
  "result": {
    "error": {
      "code": "MCP_PERMISSION_DENIED",
      "message": "MCP permission denied: agent `filter` cannot call tool `fetch_webpage`"
    }
  },
  "log": {
    "run_id": "articles-20260523",
    "agent_name": "filter",
    "server_name": "fetch-mcp",
    "tool_name": "fetch_webpage",
    "status": "denied",
    "error_message": "MCP permission denied: agent `filter` cannot call tool `fetch_webpage`",
    "success": false,
    "latency_ms": 0
  }
}
```
