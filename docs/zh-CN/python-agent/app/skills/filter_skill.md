# Filter Agent Skill 中文说明

> 原文镜像：`python-agent/app/skills/filter_skill.md`

## 任务目标

Filter Agent 负责把候选文章筛成值得总结、改写和保存的推荐结果。判断必须结合标题、正文、URL、来源、用户画像、关键词偏好、负面偏好、Milvus 语义记忆和 Neo4j 关系主题；当 Milvus 或 Neo4j 不可用时，必须基于本地规则降级评分并继续输出结构化结果。

## 输入格式

```json
{
  "run_id": "articles-20260608",
  "article": {
    "article_id": "a1",
    "url": "https://example.com/post",
    "title": "Agent workflow notes",
    "raw_text": "original article text",
    "source": "rss",
    "published_at": "2026-06-08T10:00:00Z",
    "tags": ["agent", "workflow"]
  },
  "user_profile_snapshot": {
    "user_id": "default-user",
    "interests": "AI,knowledge-management",
    "keywords": "AI,workflow",
    "topics": "AI:0.9,databases:0.2",
    "negative_preferences": "marketing fluff,重复资讯",
    "seen_urls": "https://example.com/old-post"
  },
  "mcp_policy": {
    "enable_embedding": true,
    "enable_milvus": true,
    "enable_neo4j": true
  }
}
```

## 输出格式

```json
{
  "article_id": "a1",
  "keep": true,
  "score": 8.2,
  "rank_position": 1,
  "score_breakdown": [
    {
      "dimension": "keyword_match",
      "available": true,
      "raw_score": 8.0,
      "normalized_score": 8.0,
      "weight": 1.0,
      "contribution": 8.0,
      "evidence": ["AI", "workflow"]
    }
  ],
  "recommendation_reasons": ["keyword_match 命中: AI, workflow"],
  "rejection_reasons": [],
  "filter_reasons": ["keyword_match 命中: AI, workflow"],
  "issues": [],
  "mcp_evidence": {
    "milvus_matches": [{"id": "seed-ai", "score": 0.86}],
    "neo4j_topics": [{"name": "AI", "score": 0.9}]
  }
}
```

`score` 范围为 0 到 10。`score_breakdown` 必须包含每个评分维度的可用状态、原始分、归一化分、权重、贡献和证据。`keep=true` 通常要求 `score >= recommendation.min_keep_score`，且文章不命中硬性拒绝原因。`issues` 只能放可机器处理的短字符串，例如 `filtered_out`。

## 约束条件

- 必须输出 9 个评分维度：`keyword_match`、`profile_topic`、`milvus_similarity`、`neo4j_related_topic`、`source_quality`、`freshness`、`duplicate_penalty`、`negative_preference_penalty`、`content_quality`。
- 每个维度分数必须归一化到 0 到 10，并受配置权重影响。
- 负面偏好和历史重复命中时必须降分，并在 `rejection_reasons` 或 `filter_reasons` 中说明。
- Milvus 结果只能作为语义相似度和重复惩罚信号，不能替代正文判断。
- Neo4j 主题只能用于相关主题加权和解释，不能凭空创造文章内容。
- 没有 Milvus 或 Neo4j 时必须降级评分，相关维度标记 `available=false`。
- 排序必须稳定可复测；同分时使用稳定字段排序。
- 需要满足来源和主题多样性约束，避免结果全部集中在同一来源或同一主题。
- 输出必须是 JSON object，不能包含 Markdown 代码块、自然语言前后缀或注释。

## 可调用 MCP Tool

- `embed_text`
- `embed_batch`
- `search_similar_memory`
- `query_user_interest_graph`
- `get_related_topics`

## 禁止调用 MCP Tool

- `fetch_webpage`
- `extract_main_content`
- `clean_html`
- `check_url_alive`
- `insert_memory_vector`
- `update_user_interest_graph`
- `semantic_deduplicate`
- `search_articles`
- `search_related_articles`
- `save_markdown`
- `generate_daily_report`
- `generate_weekly_report`
- `send_email`

## 失败处理

- MCP 被拒绝、超时或返回错误时，不要中断流程；记录 MCP 调用日志，并基于本地规则降级评分。
- embedding 不可用时，跳过语义记忆，只使用关键词、标题、正文、来源质量、时效和用户画像。
- Neo4j 不可用时，跳过关系主题，不要编造主题关系。
- 输入缺少 `article_id` 时使用调用方规范化 ID；缺少标题时通常不推荐。
- 命中最低保留分以下时设置 `keep=false`，并输出 `rejection_reasons`。

## 示例

输入文章标题为 `"AI Agent Workflow"`，用户兴趣包含 `"AI"`，Milvus 返回相似记忆，Neo4j 返回主题 `"agent systems"`。

```json
{
  "article_id": "a1",
  "keep": true,
  "score": 8.4,
  "rank_position": 1,
  "score_breakdown": [
    {
      "dimension": "keyword_match",
      "available": true,
      "raw_score": 8.0,
      "normalized_score": 8.0,
      "weight": 1.0,
      "contribution": 8.0,
      "evidence": ["AI"]
    },
    {
      "dimension": "milvus_similarity",
      "available": true,
      "raw_score": 8.6,
      "normalized_score": 8.6,
      "weight": 1.0,
      "contribution": 8.6,
      "evidence": ["best:0.86"]
    }
  ],
  "recommendation_reasons": ["keyword_match 命中: AI", "milvus_similarity 命中: best:0.86"],
  "rejection_reasons": [],
  "filter_reasons": ["keyword_match 命中: AI", "milvus_similarity 命中: best:0.86"],
  "issues": []
}
```
