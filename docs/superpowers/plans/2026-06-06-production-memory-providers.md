# Production Memory Providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add production OpenAI embedding, Milvus vector-store, and Neo4j interest-graph adapters while retaining contract-compatible memory modes.

**Architecture:** Keep each MCP `server.py` as a thin composition and dispatch layer. Put shared lifecycle and health behavior in `mcp-servers/common`, and put focused memory/production adapter modules beside each server. Inject SDK clients into adapters so unit tests can verify production behavior without network services.

**Tech Stack:** Python 3.12, official MCP Python SDK, OpenAI Python SDK v2, PyMilvus, Neo4j Python Driver v6, `unittest`, Docker Compose.

---

### Task 1: Common Provider Lifecycle And Health

**Files:**
- Modify: `mcp-servers/common/simple_http_mcp.py`
- Create: `mcp-servers/common/provider.py`
- Create: `mcp-servers/tests/test_provider_lifecycle.py`

- [ ] Add failing tests proving initialization failures are captured, unhealthy adapters reject calls, memory adapters report healthy, and `close()` is invoked.
- [ ] Run `python -m unittest tests.test_provider_lifecycle -v` from `mcp-servers`; expect failures because lifecycle helpers do not exist.
- [ ] Implement `ProviderState`, `ManagedProvider`, and a dynamic health callback accepted by `create_server` and `run_server`.
- [ ] Re-run `python -m unittest tests.test_provider_lifecycle -v`; expect all tests to pass.

### Task 2: Embedding Providers

**Files:**
- Create: `mcp-servers/embedding-mcp/providers.py`
- Replace: `mcp-servers/embedding-mcp/server.py`
- Create: `mcp-servers/tests/test_embedding_provider.py`
- Modify: `mcp-servers/requirements.txt`

- [ ] Add failing tests for deterministic memory embeddings, batching, bounded TTL cache, long-text chunking, weighted normalized merge, OpenAI retry, token/cost metrics, missing-key health, and dimension mismatch.
- [ ] Run `python -m unittest tests.test_embedding_provider -v`; expect import or behavior failures.
- [ ] Implement `MemoryEmbeddingProvider`, `OpenAIEmbeddingProvider`, text normalization/chunking, cache, usage metrics, and provider factory.
- [ ] Replace embedding MCP dispatch with provider calls while preserving `embed_text` and `embed_batch` consumed fields.
- [ ] Re-run embedding provider and MCP HTTP tests; expect them to pass.

### Task 3: Milvus Vector Stores

**Files:**
- Create: `mcp-servers/milvus-mcp/stores.py`
- Replace: `mcp-servers/milvus-mcp/server.py`
- Create: `mcp-servers/tests/test_milvus_store.py`
- Modify: `mcp-servers/requirements.txt`

- [ ] Add failing tests for stable IDs, exact dimension validation, memory CRUD, structured filter operators, unsafe delete rejection, vector deduplication, Milvus collection creation, and non-destructive schema mismatch handling.
- [ ] Run `python -m unittest tests.test_milvus_store -v`; expect import or behavior failures.
- [ ] Implement shared normalization/filter utilities, `MemoryVectorStore`, and injected-client `MilvusVectorStore`.
- [ ] Expose compatible existing tools plus `batch_insert_memory_vectors` and `delete_memory_vectors`.
- [ ] Re-run Milvus store and MCP HTTP tests; expect them to pass.

### Task 4: Neo4j Interest Graph Stores

**Files:**
- Create: `mcp-servers/neo4j-mcp/stores.py`
- Replace: `mcp-servers/neo4j-mcp/server.py`
- Create: `mcp-servers/tests/test_neo4j_store.py`
- Modify: `mcp-servers/requirements.txt`

- [ ] Add failing tests for stable event IDs, memory update idempotency, fixed parameterized Cypher, constraint/index initialization, ranked query results, and recommendation explanations.
- [ ] Run `python -m unittest tests.test_neo4j_store -v`; expect import or behavior failures.
- [ ] Implement normalized update events, `MemoryInterestGraphStore`, and injected-driver `Neo4jInterestGraphStore`.
- [ ] Replace Neo4j MCP dispatch while preserving aliases and existing response fields.
- [ ] Re-run Neo4j store and MCP HTTP tests; expect them to pass.

### Task 5: Python Agent Client Contract

**Files:**
- Modify: `python-agent/app/mcp/base_client.py`
- Modify: `python-agent/app/mcp/milvus_client.py`
- Modify: `python-agent/app/mcp/neo4j_client.py`
- Modify: `python-agent/app/mcp/policy.py`
- Modify: `python-agent/tests/test_mcp_client.py`
- Modify: `python-agent/tests/test_mcp_policy.py`

- [ ] Add failing tests for batch insert, delete, metadata-filter search, memory fallback schemas, and stable Neo4j `event_id` forwarding.
- [ ] Run focused Agent MCP tests; expect missing methods or permission failures.
- [ ] Extend memory tool schemas/behavior, client convenience methods, and memory-only write permissions.
- [ ] Re-run focused Agent MCP tests; expect them to pass.

### Task 6: Production Compose, Initialization, And Integration Tests

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `mcp-servers/Dockerfile`
- Create: `scripts/init_memory_services.py`
- Create: `scripts/integration_memory_services.py`
- Modify: `scripts/integration_test.ps1`
- Modify: `README.md`
- Modify: `mcp-servers/README.md`
- Modify: `mcp-servers/embedding-mcp/README.md`
- Modify: `mcp-servers/milvus-mcp/README.md`
- Modify: `mcp-servers/neo4j-mcp/README.md`

- [ ] Add a `production` Compose profile with etcd, MinIO, Milvus, Neo4j, persistent volumes, credentials from environment, and dependency health checks.
- [ ] Configure production MCP adapters without embedding secrets in source.
- [ ] Add idempotent initialization and opt-in Docker-backed integration scripts.
- [ ] Document memory startup, production startup, safe Milvus migration behavior, health checks, and opt-in OpenAI smoke testing.
- [ ] Run `docker compose config`; expect valid Compose output.

### Task 7: Verification And Requirement Audit

**Files:**
- Modify only files required by failures discovered during verification.

- [ ] Run `python -m unittest discover -s tests -v` from `mcp-servers`.
- [ ] Run `python -m unittest discover -s tests -v` from `python-agent`.
- [ ] Run `python -m compileall mcp-servers python-agent`.
- [ ] Run `docker compose config`.
- [ ] Run Docker-backed memory-service integration tests when Docker dependencies are available; otherwise report the exact blocker.
- [ ] Audit the final diff against every acceptance criterion in the design and confirm unrelated dirty-worktree changes were not reverted.
