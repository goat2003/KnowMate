# neo4j-mcp 中文说明

> 原文镜像：`mcp-servers/neo4j-mcp/README.md`

Tools：

- `query_user_interest_graph`
- `update_user_interest_graph`
- `get_related_topics`
- `explain_recommendation`

`NEO4J_PROVIDER=memory` 使用进程内兴趣图。`NEO4J_PROVIDER=neo4j` 使用 Neo4j Python Driver。

启动时会幂等创建唯一约束和索引。每个数据库查询都是固定 Cypher 加参数值；用户输入绝不会拼接进 Cypher。

兴趣更新使用稳定的 `event_id`。重复播放同一个 event 会返回 `applied=false`，不会再次增加关系权重。推荐解释会返回匹配到的兴趣和相关主题路径。
