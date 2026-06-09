# Production Candidate Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前 KnowMate 项目补齐为可部署的生产候选版本，并形成可复跑的最终验收证据。

**Architecture:** 以现有 GoFrame 后端、Python Agent、MCP Server、Web Admin 和共享数据库/向量/图数据库为服务边界，补齐容器化、健康检查、配置分层、migration、生产编排和运维文档。验收以本地 fixture/脚本优先，真实外部依赖作为生产前人工检查项记录。

**Tech Stack:** GoFrame v2、Python/FastAPI/gRPC、Node/Vite Web Admin、MySQL、Redis、Milvus、Neo4j、Docker Compose、Kubernetes manifests。

---

### Task 1: 服务与部署资产盘点

**Files:**
- Read: `README.md`
- Read: `goframe-backend/main.go`
- Read: `python-agent/app/grpc_server.py`
- Read: `mcp-servers/fetch-mcp/server.py`
- Read: `web-admin/package.json`
- Read: `shared/sql/init.sql`

- [ ] **Step 1: 记录服务入口和端口**

Run: `rg -n "Listen|Run|grpc|health|PORT|server|VITE|uvicorn|FastMCP" goframe-backend python-agent mcp-servers web-admin shared`

Expected: 输出每个服务入口、健康检查现状和配置键。

- [ ] **Step 2: 记录现有 Docker/Compose/K8s 资产**

Run: `rg --files | rg -i "dockerfile|compose|k8s|kubernetes|helm|migration|operations|architecture|release"`

Expected: 找到需要复用或新增的部署文件清单。

### Task 2: 生产运行能力

**Files:**
- Modify/Create: service Dockerfiles
- Modify/Create: service health endpoints and signal handling where missing
- Modify/Create: environment-specific config examples
- Modify/Create: migration runner script

- [ ] **Step 1: 增加可自动验证的健康检查**

Run targeted service tests after edits.

- [ ] **Step 2: 增加 migration 自动执行策略**

Run migration verification against parser/static checks or available local DB.

- [ ] **Step 3: 确认非 root 容器运行**

Run Dockerfile static checks for `USER` and healthcheck instructions.

### Task 3: 生产编排与文档

**Files:**
- Create/Modify: `docker-compose.prod.yml`
- Create/Modify: `deploy/kubernetes/*.yaml`
- Create/Modify: `RELEASE_CHECKLIST.md`
- Create/Modify: `OPERATIONS.md`
- Create/Modify: `ARCHITECTURE.md`

- [ ] **Step 1: 编写生产 Compose 示例**

Run: `docker compose -f docker-compose.prod.yml config`

Expected: Compose 配置可解析；环境变量占位符保持明确。

- [ ] **Step 2: 编写 Kubernetes manifests**

Run: `kubectl apply --dry-run=client -f deploy/kubernetes` when kubectl is available.

Expected: YAML schema 基础校验通过。

- [ ] **Step 3: 编写验收与运维文档**

Expected: 文档覆盖备份恢复、日志监控告警、发布回滚、已知限制和下一版本规划。

### Task 4: 最终验收

**Files:**
- Create/Modify: `scripts/final_acceptance.ps1`
- Possibly modify tests discovered by acceptance.

- [ ] **Step 1: 运行单元/集成测试**

Run: `go test ./... -count=1`

Run: Python test command discovered from repo.

Run: Web Admin test/build command discovered from repo.

- [ ] **Step 2: 运行生产部署静态验收**

Run: `pwsh -File scripts/final_acceptance.ps1`

Expected: 自动检查部署资产、健康检查、非 root 用户、migration、文档关键章节和可执行测试结果。

- [ ] **Step 3: 修复验收发现的问题并复跑**

Expected: 可本地证明的项目通过；外部依赖项以明确限制记录。
