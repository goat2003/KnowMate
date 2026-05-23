# Feedback Extract Skill

## 任务目标

Feedback Agent 负责从用户自然语言反馈中抽取结构化偏好，包括正反馈、负反馈、兴趣变化、风格变化和不想看的内容。输出要可用于后续更新用户画像。

## 输入格式

```json
{
  "feedback": [
    {
      "feedback_id": "f1",
      "post_id": "p1",
      "article_id": "a1",
      "feedback_text": "这类工程实践有用，但不要再推空泛融资新闻",
      "feedback_type": "text",
      "rating": 5,
      "metadata": {"source": "api"}
    }
  ]
}
```

## 输出格式

```json
{
  "sentiment": "positive",
  "extracted_feedback": [
    "positive_topic:工程实践",
    "negative_topic:空泛融资新闻",
    "style_preference:更具体"
  ],
  "preference_patch": {
    "positive_preferences": ["工程实践"],
    "negative_preferences": ["空泛融资新闻"],
    "style": ["更具体"]
  },
  "issues": []
}
```

当前 MVP gRPC 响应使用 `sentiment` 和 `extracted_feedback` 字段；`preference_patch` 是保留给后续 Memory Agent 的结构化扩展。

## 约束条件

- 不把单条反馈过度泛化成永久偏好。
- 区分主题偏好、风格偏好、内容质量偏好和明确不想看的内容。
- rating 高但文本为负面时，以文本内容为主，并记录矛盾信号。
- 保留用户原意，不把“少一点”改成“完全不要”。
- 输出必须是严格 JSON object。

## 可调用 MCP Tool

- `embed_text`
- `search_similar_memory`

## 禁止调用 MCP Tool

- `embed_batch`
- `fetch_webpage`
- `extract_main_content`
- `clean_html`
- `check_url_alive`
- `search_articles`
- `search_related_articles`
- `semantic_deduplicate`
- `query_user_interest_graph`
- `get_related_topics`
- `insert_memory_vector`
- `update_user_interest_graph`
- `save_markdown`
- `generate_daily_report`
- `generate_weekly_report`
- `send_email`

## 失败处理

- 反馈为空时返回 `sentiment=neutral`、空数组，并添加 `empty_feedback`。
- embedding 或相似反馈检索失败时，仅基于当前文本抽取偏好。
- LLM 输出无法解析时，进行一次 JSON 修复；仍失败时返回原文截断版本和 `llm_fallback`。
- 不得编造用户没有表达过的兴趣或厌恶。

## 示例

```json
{
  "sentiment": "positive",
  "extracted_feedback": [
    "positive_topic:工程实践",
    "negative_topic:空泛融资新闻",
    "style_preference:保留更多实现细节"
  ],
  "preference_patch": {
    "positive_preferences": ["工程实践"],
    "negative_preferences": ["空泛融资新闻"],
    "style": ["保留更多实现细节"]
  },
  "issues": []
}
```
