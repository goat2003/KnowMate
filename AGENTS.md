# KnowMate Project Guide

## Scope

KnowMate is an admin-first, asynchronous knowledge-content pipeline. GoFrame owns HTTP, task orchestration, and MySQL; Python Agent owns AI workflow execution over gRPC; MCP servers provide provider boundaries; Web Admin consumes the read and task APIs.

## Ownership

- `goframe-backend/`: HTTP API, task state, persistence, crawler, and gRPC client.
- `python-agent/`: article and feedback workflows, MCP policy, recommendation logic, and gRPC server.
- `mcp-servers/`: embedding, fetch, Milvus, and Neo4j adapters.
- `web-admin/`: Vite/React operational UI. Use `npm run test` and `npm run build` for UI-only changes.
- `shared/`: SQL, shared proto, configuration examples, and generated Markdown output.

## Contracts And Safety

- `POST /runs/articles` reads crawler configuration; `POST /feedback` requires `post_id` and `feedback_text`.
- Keep `shared/proto/agent.proto` and `proto/agent.proto` identical. After contract changes, regenerate bindings and run `./scripts/check_proto_contract.ps1`.
- Never commit credentials, dumps, or generated runtime output. Use `.env.example` and `scripts/check_secrets.py --all` as references.
- Treat migrations, profile rollback/rebuild, and smoke scripts as data-changing operations. Do not run them incidentally.

## Verification

- Install Python dev dependencies: `python -m pip install -r .\python-agent\requirements.txt -r .\mcp-servers\requirements.txt -r .\requirements-dev.txt`.
- Lightweight quality gate: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality_gate.ps1 -SkipDocker -SkipIntegration -SkipE2E -SkipVulnerabilityScan`.
- Full gate builds images and runs integration and E2E checks. `scripts\smoke_e2e.ps1` truncates smoke-test tables and deletes `shared\outputs\articles-*.md`.
- For Go-only work, run `go test ./... -count=1` from `goframe-backend/`; for Python-only work, run the relevant `pytest` or `unittest` suite.

## Documentation

- `README.md`, `ARCHITECTURE.md`, `OPERATIONS.md`, `SECURITY.md`, and `RELEASE_CHECKLIST.md` are the current user and operator references.
- Dated files under `docs/superpowers/` are plans or design history, not proof of current behavior.
- `docs/zh-CN/INDEX.md` maps maintained Chinese mirrors. When a change intentionally includes that directory, keep the source/mirror mapping current.

## Current Status

- Local Compose and production-candidate configuration exist, but no live deployment acceptance is recorded in this checkout.
- Read `KNOWN_LIMITATIONS.md` and `NEXT_VERSION_PLAN.md` before treating candidate infrastructure or mock-backed verification as production-ready.
