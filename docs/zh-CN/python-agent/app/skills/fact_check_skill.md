# Fact Check Skill 中文说明

> 原文镜像：`python-agent/app/skills/fact_check_skill.md`

## 任务目标

Check Agent 负责检查摘要和推文是否忠于原文、是否夸大、链接是否有效、是否重复推荐，以及输出格式是否符合发布要求。

## 输入格式

```json
{
  "article": {
    "article_id": "a1",
    "url": "https://example.com/post",
    "title": "Agent workflow notes",
    "raw_text": "original article text"
  },
  "summary": "这篇文章主要说明了……",
  "post_text": "【知识笔记】……",
  "mcp_policy": {
    "enable_fetch": true,
    "enable_milvus": true
  }
}
```

## 输出格式

```json
{
  "check_pass": true,
  "issues": [],
  "evidence": {
    "url_alive": true,
    "duplicate": false,
    "format_valid": true
  }
}
```

`issues` 使用短字符串，例如 `missing_summary`、`missing_post_text`、`missing_url`、`dead_url`、`unsupported_claim`、`duplicate_recommendation`、`invalid_format`。

## 约束条件

- 必须检查 summary 和 post_text 是否存在。
- 必须检查 URL 是否存在；如果允许调用 MCP，则用 `check_url_alive` 检查链接可访问性。
- 发现推文比原文更夸张、更确定或加入新事实时，必须记录 `unsupported_claim`。
- 发现相似内容已经推荐过时，必须记录 `duplicate_recommendation`。
- 不能为了通过检查而改写内容；只能返回检查结果和问题。
- `check_pass=true` 只能在必需字段存在且没有严重问题时返回。

## 可调用 MCP Tool

- `fetch_webpage`
- `check_url_alive`
- `search_similar_memory`
- `semantic_deduplicate`

## 禁止调用 MCP Tool

- `embed_text`
- `embed_batch`
- `extract_main_content`
- `clean_html`
- `search_articles`
- `search_related_articles`
- `query_user_interest_graph`
- `get_related_topics`
- `insert_memory_vector`
- `update_user_interest_graph`
- `save_markdown`
- `generate_daily_report`
- `generate_weekly_report`
- `send_email`

## 失败处理

- URL 检查失败时不要阻塞整个流程，添加 `url_check_failed`。
- 去重检查失败时添加 `dedupe_check_failed`，但不要凭空判断重复。
- 原文缺失时只能做字段和格式检查，并添加 `missing_raw_text`。
- MCP 失败必须记录日志，不能把失败结果当作真实证据。

## 示例

```json
{
  "check_pass": false,
  "issues": ["dead_url", "unsupported_claim"],
  "evidence": {
    "url_alive": false,
    "duplicate": false,
    "format_valid": true
  }
}
```
