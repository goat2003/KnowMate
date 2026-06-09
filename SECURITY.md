# SECURITY.md

## 安全边界

KnowMate 由 GoFrame HTTP API、Python gRPC Agent、MCP Servers 和数据库组成。生产环境默认应把 GoFrame HTTP API 放在可信反向代理后，并设置：

- `GOFRAME_API_TOKEN`：HTTP Bearer token 或 `X-API-Key`。
- `AGENT_GRPC_AUTH_TOKEN`：GoFrame 到 Python Agent 的内部 gRPC token，两端必须一致。
- `GOFRAME_MAX_REQUEST_BODY_BYTES`、`GOFRAME_RATE_LIMIT_BURST`：请求大小和基础速率限制。

`GET /health` 保持公开用于存活检查；配置了 `GOFRAME_API_TOKEN` 后，其他 HTTP 路由都需要鉴权。Python gRPC 配置了 `AGENT_GRPC_AUTH_TOKEN` 后，所有 RPC 都需要 `authorization: Bearer <token>` 或 `x-api-key` metadata。

## MCP 最小权限

所有 MCP 调用必须经过 `python-agent/app/mcp/policy.py` 的 `MCPPolicy.check(...)`。未知 Agent 默认拒绝，未在 allowlist 中的 Tool 默认拒绝。

高风险 Tool 默认禁用，即使写在普通权限表中也不会放行：

- 邮件发送：`send_email`
- 文件读写删除：`read_file`、`write_file`、`delete_file`、`save_markdown`
- 报告生成或外发：`generate_daily_report`、`generate_weekly_report`

如确需启用，必须在代码中显式传入 `high_risk_allowlist`，并在变更说明中写清楚业务理由、允许目录或收件人范围、审计日志字段和回滚方式。

## SSRF 防护

`fetch-mcp` 只允许绝对 `http` / `https` URL，禁止：

- `localhost`、回环地址、私网地址、链路本地地址、保留地址、组播地址。
- 云元数据地址，例如 `169.254.169.254`、`metadata.google.internal`、`fd00:ec2::254`。
- 带 userinfo 的 URL，例如 `https://user:pass@example.com`。
- DNS 解析后落到受限地址的域名。
- HTTP 重定向。

响应体通过 `FETCH_MAX_RESPONSE_BYTES` 限制，默认 `2097152` 字节。

## 文件路径防护

当前仓库没有独立 File MCP。GoFrame Markdown 输出只允许写入 `output.dir` 配置目录，文件名由 `run_id` 经白名单净化得到，只保留字母、数字、`.`、`_`、`-`，并在写入前校验最终路径没有逃逸输出目录。

如未来新增 File MCP，必须采用允许目录配置，拒绝绝对路径、`..`、符号链接逃逸和未授权扩展名，并默认禁用写入/删除能力。

## 注入防护

SQL 和 Cypher 查询必须使用参数化 API。Milvus 过滤器、Neo4j Cypher 和 MySQL 查询需要保留现有 allowlist / 参数化测试，不允许拼接用户输入生成查询语句。

外部网页内容、RSS 内容、用户反馈和 MCP 返回内容一律视为不可信数据。LLM 调用会把业务输入放入 `untrusted_payload` 信封，并在 system prompt 中明确要求模型不得服从外部内容里的指令。模型输出经过 Pydantic schema 校验和安全短语扫描，疑似覆盖系统指令、泄露 prompt 或伪造工具调用的输出会触发 fallback。

## 密钥与日志

不要提交真实密钥。生产密钥通过环境变量或 `*_FILE` mounted secret 提供。

日志会脱敏 `api_key`、`authorization`、`token`、`password`、`cookie` 等敏感字段。新增日志字段时应复用 `redact_sensitive`，不要直接打印请求头、DSN、MCP payload 或 LLM 原始响应。

## 验证

安全相关改动至少运行：

```powershell
cd goframe-backend
go test ./internal/handler ./internal/config ./internal/logic/harness ./internal/grpcclient -count=1

cd ..
python -m pytest python-agent/tests/test_mcp_policy.py python-agent/tests/test_llm_tool.py python-agent/tests/test_grpc_security.py mcp-servers/tests/test_fetch_security.py -q
```
