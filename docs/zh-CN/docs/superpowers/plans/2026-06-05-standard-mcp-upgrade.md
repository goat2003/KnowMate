# 标准 MCP 升级实施计划

> 原文镜像：`docs/superpowers/plans/2026-06-05-standard-mcp-upgrade.md`

> **给 agentic workers：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施本计划。步骤使用 checkbox（`- [ ]`）语法追踪。

**目标：** 用官方 MCP Python SDK 替换自定义 MCP JSON-RPC 层，同时保留本地开发的韧性和便利性。

**架构：** 每个配置的 MCP server 独立选择 `memory`、`stdio` 或 `streamable_http`。统一同步 facade 在后台 asyncio loop 上持有长期官方 SDK session；启动时发现并缓存 tools，校验 schemas，并在向 Agent 返回结构化结果前应用 timeout、retry、circuit breaker、fallback 和脱敏日志。

**技术栈：** Python 3.10+、官方 `mcp` Python SDK v1、`jsonschema`、`unittest`、gRPC、Docker Compose。

---

### Task 1：配置与 Client 契约

**文件：**

- 修改：`python-agent/app/config.py`
- 新建：`python-agent/app/mcp/transport.py`
- 测试：`python-agent/tests/test_mcp_client.py`

- [ ] 为按 server 混合配置和 discovery cache 编写失败测试。
- [ ] 运行 `python -m unittest tests.test_mcp_client -v`，确认失败能说明缺少配置/client API。
- [ ] 增加 `McpServerSettings`，以及包含 `start`、`list_tools`、`call`、`close` 的统一 transport contract。
- [ ] 重新运行聚焦测试。

### Task 2：韧性、校验与日志

**文件：**

- 修改：`python-agent/app/mcp/base_client.py`
- 修改：`python-agent/app/mcp/transport.py`
- 测试：`python-agent/tests/test_mcp_client.py`
- 测试：`python-agent/tests/test_mcp_policy.py`

- [ ] 为 permission short-circuit、输入/输出 Schema 校验、timeout retry、circuit opening、memory fallback 和敏感字段脱敏编写失败测试。
- [ ] 运行聚焦测试并确认出现预期失败。
- [ ] 在统一 MCP 边界实现最小所需行为。
- [ ] 重新运行聚焦测试。

### Task 3：官方 MCP Servers

**文件：**

- 替换：`mcp-servers/common/simple_http_mcp.py`
- 修改：`mcp-servers/*-mcp/server.py`
- 修改：`mcp-servers/tests/test_http_mcp.py`

- [ ] 用官方 SDK `ClientSession` 集成测试替换自定义 `/rpc` 断言。
- [ ] 运行 server 测试，确认它在自定义 server 上失败。
- [ ] 通过官方 SDK 注册现有 tool handlers，并支持 `stdio` 与 Streamable HTTP 启动。
- [ ] 重新运行 server 集成测试。

### Task 4：应用生命周期与文档

**文件：**

- 修改：`python-agent/app/workflow/graph.py`
- 修改：`python-agent/app/grpc_server.py`
- 修改：`python-agent/server.py`
- 修改：`python-agent/config.yaml`
- 修改：`python-agent/requirements.txt`
- 修改：`python-agent/pyproject.toml`
- 修改：`mcp-servers/Dockerfile`
- 修改：`docker-compose.yml`
- 修改：`.env.example`
- 修改：`README.md`
- 修改：`mcp-servers/README.md`

- [ ] 将 MCP startup discovery 和 shutdown cleanup 接入 Agent service 生命周期。
- [ ] 添加 SDK 依赖和混合 transport 配置示例。
- [ ] 更新 Docker 默认值，指向 Streamable HTTP MCP endpoints。
- [ ] 记录本地 memory、stdio 和 HTTP 启动命令。

### Task 5：验证

- [ ] 在 `python-agent` 目录运行 `python -m unittest discover -s tests -v`。
- [ ] 在 `mcp-servers` 目录运行 `python -m unittest discover -s tests -v`。
- [ ] 运行 `python -m compileall python-agent mcp-servers`。
- [ ] 审查 `git diff`，确认没有无关改动，并覆盖需求。
