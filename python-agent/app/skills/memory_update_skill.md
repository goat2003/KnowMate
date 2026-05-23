# Memory Update Skill

## 任务目标

Memory Agent 负责把反馈写入语义记忆，更新 Neo4j 主题关系，调整兴趣权重，并生成新的 `user_profile_snapshot`。更新必须可解释、可回滚，不因为单次反馈造成极端变化。

## 输入格式

```json
{
  "run_id": "feedback-20260523",
  "user_profile_snapshot": {
    "user_id": "default-user",
    "interests": "AI,knowledge-management",
    "negative_preferences": "marketing fluff",
    "feedback_count": "3"
  },
  "sentiment": "positive",
  "extracted_feedback": [
    "positive_topic:工程实践",
    "negative_topic:空泛融资新闻"
  ]
}
```

## 输出格式

```json
{
  "updated_profile_snapshot": {
    "user_id": "default-user",
    "interests": "AI,knowledge-management,工程实践",
    "negative_preferences": "marketing fluff,空泛融资新闻",
    "feedback_count": "4",
    "last_feedback_sentiment": "positive",
    "latest_feedback": "positive_topic:工程实践 | negative_topic:空泛融资新闻"
  },
  "memory_operations": [
    {"tool": "embed_text", "status": "success"},
    {"tool": "update_user_interest_graph", "status": "success"}
  ],
  "issues": []
}
```

## 约束条件

- 反馈写入 Milvus 前必须生成 embedding；embedding 失败时不能写入向量。
- Neo4j 更新只写主题、偏好和关系权重，不写未经验证的文章事实。
- 兴趣权重应渐进更新，避免单次反馈直接覆盖长期偏好。
- 负反馈要保留到 `negative_preferences` 或对应权重，不要简单丢弃。
- `user_profile_snapshot` 的值应保持可序列化字符串或简单结构。

## 可调用 MCP Tool

- `embed_text`
- `insert_memory_vector`
- `search_similar_memory`
- `update_user_interest_graph`
- `query_user_interest_graph`
- `get_related_topics`

## 禁止调用 MCP Tool

- `embed_batch`
- `fetch_webpage`
- `extract_main_content`
- `clean_html`
- `check_url_alive`
- `search_articles`
- `search_related_articles`
- `semantic_deduplicate`
- `save_markdown`
- `generate_daily_report`
- `generate_weekly_report`
- `send_email`

## 失败处理

- `embed_text` 失败时跳过 `insert_memory_vector`，但仍更新本地 snapshot。
- `insert_memory_vector` 失败时记录 `memory_vector_insert_failed`，不影响 Neo4j 更新。
- `update_user_interest_graph` 失败时记录 `interest_graph_update_failed`，不回滚本地 snapshot。
- MCP 失败或拒绝必须进入 `mcp_call_logs`，不能隐式吞掉。

## 示例

```json
{
  "updated_profile_snapshot": {
    "user_id": "default-user",
    "interests": "AI,knowledge-management,工程实践",
    "negative_preferences": "marketing fluff,空泛融资新闻",
    "feedback_count": "4",
    "last_feedback_sentiment": "positive",
    "latest_feedback": "positive_topic:工程实践 | negative_topic:空泛融资新闻"
  },
  "memory_operations": [
    {"tool": "embed_text", "status": "success"},
    {"tool": "update_user_interest_graph", "status": "success"}
  ],
  "issues": []
}
```
