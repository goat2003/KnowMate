# Rewrite Post Skill 中文说明

> 原文镜像：`python-agent/app/skills/rewrite_post_skill.md`

## 任务目标

Rewrite Agent 负责把中文总结改写成适合发布的知识推文。推文要有观点、有信息密度、可读性强，并尽量贴合用户写作风格；不能标题党、不能营销号、不能夸大原文。

## 输入格式

```json
{
  "article": {
    "article_id": "a1",
    "url": "https://example.com/post",
    "title": "Agent workflow notes",
    "source": "rss"
  },
  "summary": "这篇文章主要说明了……",
  "user_profile_snapshot": {
    "style": "dense, practical",
    "tone": "calm, technical"
  }
}
```

## 输出格式

```json
{
  "post_text": "【知识笔记】标题\n\n……\n\n原文：https://example.com/post",
  "issues": []
}
```

`post_text` 必须是完整 Markdown 文本，包含原文链接。`issues` 只能放短字符串，例如 `missing_summary`、`missing_url`、`style_fallback`。

## 约束条件

- 不使用标题党句式，例如“震惊”“彻底颠覆”“必看”“封神”。
- 不使用营销号语气，例如过度煽动、空泛号召、无依据承诺。
- 观点必须来自总结或原文，不能新增事实。
- 保持信息密度，避免大段空话。
- 可以使用列表组织内容，但不要制造原文没有的步骤或结论。
- 必须符合用户画像中的写作风格；没有画像时默认冷静、实用、技术向。

## 可调用 MCP Tool

当前 MVP 中 Rewrite Agent 不需要调用 MCP Tool。

## 禁止调用 MCP Tool

- `embed_text`
- `embed_batch`
- `fetch_webpage`
- `extract_main_content`
- `clean_html`
- `check_url_alive`
- `search_similar_memory`
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

- 缺少 summary 时返回空推文风险，并添加 `missing_summary`。
- 缺少 URL 时仍可生成正文，但必须添加 `missing_url`。
- LLM 输出解析失败时，进行一次 JSON 修复；仍失败时使用模板推文并添加 `llm_fallback`。
- 不能通过调用 MCP 补充未经验证的事实。

## 示例

```json
{
  "post_text": "【知识笔记】Agent 工作流为什么要拆节点\n\n这篇文章的核心价值是：把内容处理拆成 Filter、Summary、Rewrite、Check 几个节点，可以让每一步的失败、重试和日志都更清楚。\n\n可关注的点：\n1. 过滤阶段决定是否值得处理，避免浪费生成成本。\n2. 检查阶段约束摘要和推文，降低夸大和格式错误。\n3. 反馈可以继续更新用户画像，让后续推荐更贴近偏好。\n\n原文：https://example.com/post",
  "issues": []
}
```
