# Production Memory Providers Design

Date: 2026-06-06

## Goal

Replace the current Milvus, Neo4j, and embedding mock-only MCP server
implementations with production-capable adapters while preserving deterministic
in-memory implementations for local development and automated tests.

The implementation must preserve the existing MCP boundary. Python Agent code
continues to call MCP tools through the unified MCP client and never imports or
calls MCP server internals.

## Confirmed Decisions

- Use provider/repository interfaces with separate memory and production
  implementations.
- Use the OpenAI-compatible Embeddings API with
  `text-embedding-3-large` as the default real embedding model.
- Keep GPT-5.5 for Agent generation/reasoning calls, not embedding generation.
- Use `3072` as the default embedding dimension, configurable through
  environment variables.
- Name the Milvus collection `user_memory_vectors`.
- If an existing Milvus collection has an incompatible schema or vector
  dimension, do not drop, recreate, or mutate it automatically. Mark the
  service unhealthy and reject affected operations until an administrator
  performs an explicit migration or selects a new collection.
- Keep MCP processes alive when production dependencies are unavailable.
  Health checks report the dependency error and MCP tool calls return
  structured failures so the Agent's existing retry, circuit breaker, and
  memory fallback behavior can degrade safely.
- Never store API keys or database passwords in the repository.

## Considered Approaches

### Provider and Repository Layers

Each MCP server exposes its current tool boundary and delegates work to a small
interface implemented by both memory and production adapters.

This is the selected approach because it gives memory and production modes the
same behavior contract, makes failure behavior independently testable, and
keeps database SDK details out of MCP request dispatch.

### Production Branches Inside Existing Server Files

Adding `if mock_mode` branches directly to each `server.py` would touch fewer
files, but would mix MCP schemas, lifecycle, caching, retries, database queries,
and business rules. It was rejected because the resulting modules would be
difficult to test and maintain.

### Separate Internal Microservices

Running database adapters behind additional network services would give strong
isolation, but would add unnecessary deployment and failure surfaces for the
current project. It was rejected as out of scope.

## Architecture

Each MCP server keeps a thin composition and tool-dispatch layer:

```text
Official MCP Server
  -> tool input validation
  -> provider/repository interface
  -> memory adapter or production adapter
  -> normalized result
  -> tool output validation
```

The three services use these interfaces:

- `EmbeddingProvider`
  - `embed_text(text, options)`
  - `embed_batch(texts, options)`
  - `health()`
  - `close()`
- `VectorStore`
  - `initialize()`
  - `upsert(item)`
  - `upsert_batch(items)`
  - `search(vector, limit, metadata_filter)`
  - `delete(ids, metadata_filter)`
  - `deduplicate(items, threshold, metadata_filter)`
  - `health()`
  - `close()`
- `InterestGraphStore`
  - `initialize()`
  - `query_user_interests(user_id, limit)`
  - `update_user_interests(event)`
  - `get_related_topics(topic, limit)`
  - `explain_recommendation(user_id, article)`
  - `health()`
  - `close()`

Production SDK clients are created once per MCP process and closed during
server shutdown. The Neo4j driver is process-lifetime and thread-safe. Milvus
and OpenAI clients are also reused rather than recreated per tool call.

## Embedding Provider

### Configuration

- `EMBEDDING_PROVIDER`: `memory` or `openai`
- `EMBEDDING_MODEL`: default `text-embedding-3-large`
- `EMBEDDING_DIMENSION`: default `3072` in real mode and configurable in
  memory mode
- `OPENAI_BASE_URL`: default `https://api.openai.com/v1`
- `OPENAI_API_KEY`: required only for real OpenAI mode
- `EMBEDDING_TIMEOUT_SECONDS`
- `EMBEDDING_MAX_RETRIES`
- `EMBEDDING_BATCH_SIZE`
- `EMBEDDING_MAX_CHARS_PER_CHUNK`
- `EMBEDDING_MAX_CHUNKS`
- `EMBEDDING_CACHE_SIZE`
- `EMBEDDING_CACHE_TTL_SECONDS`
- `EMBEDDING_COST_PER_MILLION_TOKENS_USD`: optional

The provider must not expose `OPENAI_API_KEY` in health responses, logs, MCP
results, or exceptions.

### Text Processing

Input text is normalized before hashing and caching. Empty text is rejected.
Text longer than the configured safe chunk size is split on paragraph or
sentence boundaries where possible, with a hard character boundary as a
fallback. The total number of chunks is capped.

Each chunk is embedded through a batched API request. Multi-chunk embeddings
are combined using a token-weighted average and then L2-normalized. The
provider validates that every returned vector has the configured dimension.

The cache key includes provider name, base URL identity, model, dimension, and
the normalized text hash. Cached values include the vector and usage metadata.
The initial cache is a process-local bounded TTL/LRU cache. Distributed cache
support is outside this scope.

### Usage and Cost

Embedding results include:

- `embedding`
- `dim`
- `model`
- `provider`
- `mock`
- `cache_hit`
- `token_count`
- `latency_ms`
- `estimated_cost_usd`
- `truncated`
- `chunk_count`

Token usage is taken from the provider response when available. Cost is only
calculated when `EMBEDDING_COST_PER_MILLION_TOKENS_USD` is configured; otherwise
it is `null`. This avoids hard-coding pricing that may become stale.

Logs record text hashes and lengths, not full long text. Sensitive metadata
keys use the existing MCP log redaction rules.

## Milvus Vector Store

### Collection Schema

The production adapter creates and validates `user_memory_vectors` with:

- `id`: `VARCHAR`, primary key, stable and application-generated
- `embedding`: `FLOAT_VECTOR`, configured dimension
- `user_id`: `VARCHAR`
- `source`: `VARCHAR`
- `topic`: `VARCHAR`
- `external_id`: `VARCHAR`
- `content_hash`: `VARCHAR`
- `created_at`: integer Unix timestamp
- `metadata_json`: JSON

The vector index uses `HNSW` with `COSINE`. Index construction and search
parameters are configurable with production-oriented defaults.

On startup, the adapter:

1. Connects to Milvus.
2. Creates the collection and index when absent.
3. Validates every required field, primary-key type, vector type, dimension,
   and metric when present.
4. Loads the collection.
5. Records initialization status for `/health`.

Any incompatible existing schema makes the service unhealthy. The adapter does
not automatically delete or rebuild production data.

### Stable IDs and Writes

Callers may provide an explicit ID. If omitted, the server generates:

```text
sha256(user_id + "\0" + source + "\0" + (external_id or content_hash))
```

`content_hash` is derived from normalized source content when not explicitly
provided. The store uses upsert so retries and replay of the same logical
record update the same primary key rather than create duplicates.

All inserts validate that the vector length exactly matches the configured
dimension. Dimension mismatch is a structured validation error and is never
silently truncated, padded, or projected.

### Metadata Filters

MCP callers pass a structured filter object. They cannot pass raw Milvus filter
expressions. Supported fields are explicitly allowlisted. Initial operators:

- `eq`
- `in`
- `gte`
- `lte`

The adapter validates field names, operators, values, and list sizes before
compiling the filter expression. String values are safely escaped by the
compiler. Invalid filters are rejected before any database call.

### Search, Delete, and Deduplication

- Search accepts a vector, limit, optional minimum score, and structured
  metadata filter.
- Delete accepts explicit stable IDs or a structured metadata filter. An empty
  unqualified delete is rejected.
- Batch insert validates every item before writing. Invalid batches do not
  partially write.
- Semantic deduplication compares vectors within the incoming batch and,
  optionally, searches existing collection records using the same metadata
  scope. Items at or above the threshold return a canonical ID and are not
  inserted again.

Memory mode implements the same exact-dimension checks, stable ID generation,
filter semantics, CRUD behavior, and vector-based deduplication.

## Neo4j Interest Graph

### Graph Model

```text
(:User {id})
  -[:INTERESTED_IN {weight, updated_at, last_event_id}]->
(:Topic {name})

(:Topic)-[:RELATED_TO {weight}]->(:Topic)

(:InterestEvent {id, user_id, created_at})
```

Constraints and indexes are created idempotently during initialization:

- Unique constraint on `User.id`
- Unique constraint on `Topic.name`
- Unique constraint on `InterestEvent.id`
- Indexes needed by the fixed query patterns

### Parameterized Cypher

Every query is a fixed Cypher statement stored in code. Values are supplied
only through Neo4j driver parameters. User input is never concatenated into
Cypher identifiers, labels, relationship types, predicates, or values.

The adapter uses one process-lifetime driver, verifies connectivity during
startup, executes reads with read routing, executes writes in managed
transactions, and closes the driver on shutdown.

### Idempotent Interest Updates

Every update carries a stable `event_id`. If the caller does not provide one,
the server derives it from the user ID and normalized update payload.

The write transaction first merges `InterestEvent {id: $event_id}`. Relationship
weights and timestamps are updated only when the event is newly created.
Replaying the same event therefore returns success without applying the weight
change again.

Explicit topic weights, snapshot interests, and extracted feedback are
normalized into one event model before reaching either the memory or Neo4j
adapter. Weight values remain in the inclusive `0..1` range.

### Queries and Recommendation Explanations

User-interest queries return ranked topics with weights. Related-topic queries
traverse fixed `RELATED_TO` paths with bounded depth and result count.

Recommendation explanation accepts structured article fields and topic names.
It returns:

- directly matched user topics
- related-topic paths that contributed to the result
- relationship and interest weights
- a normalized score
- human-readable reason strings derived from the returned graph data

The explanation is deterministic and does not require an LLM call.

## MCP Tool Contract Changes

Existing tool names remain available for compatibility:

- `embed_text`
- `embed_batch`
- `insert_memory_vector`
- `search_similar_memory`
- `search_related_articles`
- `search_articles`
- `semantic_deduplicate`
- `query_user_interest_graph`
- `update_user_interest_graph`
- `get_related_topics`
- `explain_recommendation`

Milvus adds:

- `batch_insert_memory_vectors`
- `delete_memory_vectors`

Existing tools gain optional structured fields such as `user_id`,
`metadata_filter`, `minimum_score`, and `event_id`. Output schemas gain provider
and operation metadata while preserving currently consumed fields.

Python Agent's `MilvusClient` gains convenience methods for batch insert,
delete, and structured-filter searches. The Agent permission policy grants new
write tools only to the `memory` Agent. All calls still pass through
`BaseMcpClient` for permission checks, schema validation, logging, timeout,
retry, circuit breaking, and fallback.

## Lifecycle and Health

Each server initializes its adapter before accepting useful production calls.
Initialization errors are captured as dependency state instead of terminating
the process.

`GET /health` returns a non-success HTTP status when a configured production
dependency is unavailable or incompatible, with a body containing:

- MCP server name
- operating mode
- dependency status
- provider/database identity without credentials
- configured model, collection, and vector dimension where applicable
- last initialization or health error

Memory mode reports healthy without requiring external services.

Tool calls made while a production adapter is unavailable return a structured
MCP tool error. The Python Agent handles this through its existing resilience
layer and may fall back to its in-process memory MCP implementation when
`MCP_MEMORY_FALLBACK=true`.

## Docker and Initialization

Development remains lightweight:

```text
docker compose up
```

uses memory MCP provider modes unless explicitly overridden.

A `production` Compose profile adds:

- Milvus standalone
- etcd
- MinIO
- Neo4j
- production-mode embedding, Milvus, and Neo4j MCP servers

Persistent volumes are declared for Milvus, MinIO, etcd, and Neo4j. Services
use dependency-level health checks. MCP production services depend on healthy
database services but still retain their own health reporting.

Initialization scripts are responsible only for safe, idempotent setup:

- Milvus collection creation and schema validation
- Neo4j constraints, indexes, and optional seed topic relationships

No initialization script drops or recreates existing production data.

The OpenAI API key is supplied through `OPENAI_API_KEY` or a Docker secret and
is not included in Compose defaults or committed files.

## Failure Handling

- Missing OpenAI key in real mode: embedding MCP stays alive, reports unhealthy,
  and returns structured tool errors.
- OpenAI timeout or transient error: provider-level bounded retry applies,
  followed by an MCP tool error. The Agent may perform its own bounded retry
  and fallback.
- Embedding dimension mismatch: reject the response or write immediately.
- Milvus unavailable: service stays alive and reports unhealthy; tools fail
  without crashing the Agent task.
- Milvus collection schema mismatch: service stays alive, reports the exact
  mismatch, and rejects operations without mutation.
- Neo4j unavailable: service stays alive and reports unhealthy; tools fail
  without crashing the Agent task.
- Invalid metadata filter or unsafe delete: reject before calling Milvus.
- Duplicate Neo4j event: return success with `applied=false`.

## Testing Strategy

### Unit Tests

Embedding tests cover:

- deterministic memory vectors
- real provider batching
- cache hits and cache-key isolation
- timeout and retry behavior
- usage and configurable cost calculation
- safe chunking and combined-vector normalization
- provider dimension mismatch
- missing-key unhealthy behavior

Milvus tests cover:

- collection creation and validation
- incompatible dimension rejection without destructive calls
- stable ID generation
- single and batch upsert
- exact dimension validation
- structured metadata filter compilation and invalid-filter rejection
- search and delete
- unsafe empty delete rejection
- batch and collection semantic deduplication

Neo4j tests cover:

- idempotent constraint and index initialization
- parameterized query execution
- repeated event updates applying once
- ranked interest queries
- related-topic queries
- recommendation explanation
- driver lifecycle and unavailable dependency behavior

SDK clients are injected into production adapters so unit tests can use fakes
that verify calls and parameters without requiring network services.

### Integration Tests

Docker-backed integration tests connect to actual Milvus and Neo4j services and
verify:

- Milvus collection schema, CRUD, metadata filtering, stable upsert, and
  semantic deduplication
- Neo4j constraints, parameterized workflows, idempotent updates, queries, and
  explanations
- MCP `tools/list` and `tools/call` over Streamable HTTP
- health behavior while dependencies are healthy and unavailable
- Agent permission denial, timeout, retry, circuit breaker, and memory fallback

Real OpenAI network testing is opt-in and skipped unless both an explicit smoke
test flag and `OPENAI_API_KEY` are present. Normal CI uses a fake OpenAI client
to verify the embedding contract without cost or network dependency.

### Regression Verification

The existing Python Agent, MCP server, Go backend, protobuf contract, and smoke
test suites remain part of the final verification. Test commands and production
startup instructions are documented in the root README.

## Acceptance Criteria

- Memory mode works without Milvus, Neo4j, or an OpenAI key.
- Real embedding mode supports single and batch calls, cache, timeout, retry,
  usage metrics, configurable cost, and safe long-text handling.
- `user_memory_vectors` is safely created and validated.
- Milvus supports stable single/batch upsert, search, structured metadata
  filters, delete, and vector-based semantic deduplication.
- No vector dimension mismatch is silently accepted or destructively migrated.
- Neo4j constraints and indexes are created idempotently.
- No Cypher query concatenates user-provided values.
- Replaying the same interest event does not change relationship weights twice.
- Recommendation explanations include graph-derived reasons.
- Production dependency failures do not crash the MCP process or the Agent
  task.
- Docker production profile, initialization scripts, health checks, integration
  tests, and README instructions are present and verified.
