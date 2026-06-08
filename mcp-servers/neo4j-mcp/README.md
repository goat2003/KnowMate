# neo4j-mcp

Tools:

- `query_user_interest_graph`
- `update_user_interest_graph`
- `get_related_topics`
- `explain_recommendation`

`NEO4J_PROVIDER=memory` uses an in-process interest graph.
`NEO4J_PROVIDER=neo4j` uses the Neo4j Python Driver.

Startup creates unique constraints and indexes idempotently. Every database
query is fixed Cypher with parameter values; user input is never concatenated
into Cypher.

Interest updates use a stable `event_id`. Replaying the same event returns
`applied=false` and does not increment relationship weights again.
Recommendation explanations return matched interests and related-topic paths.
