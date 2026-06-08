# Standard MCP Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the custom MCP JSON-RPC layer with the official MCP Python SDK while preserving resilient local development behavior.

**Architecture:** Each configured MCP server independently selects `memory`, `stdio`, or `streamable_http`. A unified synchronous facade owns long-lived official SDK sessions on a background asyncio loop, discovers and caches tools during startup, validates schemas, and applies timeout, retry, circuit breaker, fallback, and redacted logging before returning structured results to Agents.

**Tech Stack:** Python 3.10+, official `mcp` Python SDK v1, `jsonschema`, `unittest`, gRPC, Docker Compose.

---

### Task 1: Configuration And Client Contract

**Files:**
- Modify: `python-agent/app/config.py`
- Create: `python-agent/app/mcp/transport.py`
- Test: `python-agent/tests/test_mcp_client.py`

- [ ] Write failing tests for mixed per-server configuration and discovery caching.
- [ ] Run `python -m unittest tests.test_mcp_client -v` and confirm failures describe missing configuration/client APIs.
- [ ] Add `McpServerSettings` plus a unified transport contract with `start`, `list_tools`, `call`, and `close`.
- [ ] Re-run the focused tests.

### Task 2: Resilience, Validation, And Logging

**Files:**
- Modify: `python-agent/app/mcp/base_client.py`
- Modify: `python-agent/app/mcp/transport.py`
- Test: `python-agent/tests/test_mcp_client.py`
- Test: `python-agent/tests/test_mcp_policy.py`

- [ ] Write failing tests for permission short-circuit, input/output Schema validation, timeout retry, circuit opening, memory fallback, and sensitive-field redaction.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement the minimum behavior at the unified MCP boundary.
- [ ] Re-run focused tests.

### Task 3: Official MCP Servers

**Files:**
- Replace: `mcp-servers/common/simple_http_mcp.py`
- Modify: `mcp-servers/*-mcp/server.py`
- Modify: `mcp-servers/tests/test_http_mcp.py`

- [ ] Replace custom `/rpc` assertions with an official SDK `ClientSession` integration test.
- [ ] Run the server test and confirm it fails against the custom server.
- [ ] Register existing tool handlers through the official SDK and support `stdio` plus Streamable HTTP startup.
- [ ] Re-run the server integration test.

### Task 4: Application Lifecycle And Documentation

**Files:**
- Modify: `python-agent/app/workflow/graph.py`
- Modify: `python-agent/app/grpc_server.py`
- Modify: `python-agent/server.py`
- Modify: `python-agent/config.yaml`
- Modify: `python-agent/requirements.txt`
- Modify: `python-agent/pyproject.toml`
- Modify: `mcp-servers/Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `mcp-servers/README.md`

- [ ] Wire MCP startup discovery and shutdown cleanup into the Agent service lifecycle.
- [ ] Add SDK dependencies and mixed transport configuration examples.
- [ ] Update Docker defaults to Streamable HTTP MCP endpoints.
- [ ] Document local memory, stdio, and HTTP startup commands.

### Task 5: Verification

- [ ] Run `python -m unittest discover -s tests -v` from `python-agent`.
- [ ] Run `python -m unittest discover -s tests -v` from `mcp-servers`.
- [ ] Run `python -m compileall python-agent mcp-servers`.
- [ ] Review `git diff` for unrelated changes and requirement coverage.
