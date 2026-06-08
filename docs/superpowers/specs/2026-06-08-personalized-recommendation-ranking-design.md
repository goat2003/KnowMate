# 个性化推荐排序系统设计

日期：2026-06-08

## 目标

将当前 Python `FilterAgent` 的简单规则打分升级为可解释、可配置、可降级、可重复测试的个性化推荐排序系统。

本设计覆盖：

- 9 个评分维度的统一建模
- 0 到 10 的归一化综合分
- 每个评分维度的明细输出
- 推荐原因与拒绝原因输出
- 最低保留分数
- 来源与主题多样性约束
- Milvus 和 Neo4j 不可用时的降级评分
- 排序结果的确定性
- 离线推荐评估脚本与指标
- Python Agent、protobuf、GoFrame 接入边界

## 已确认决策

- 采用“兼容扩展”方案：保留现有文章处理流程，只替换 Filter Agent 内部评分与排序逻辑。
- 新增独立推荐排序模块，Filter Agent 调用该模块，不把所有逻辑继续堆在 `filter_agent.py`。
- 综合分统一为 `0..10`，现有 `score` 字段继续存在，但语义从 `0..1` 变为 `0..10`。
- 每个评分维度输出结构化明细，便于调试、展示和离线评估。
- gRPC/protobuf 增加解释字段，避免评分明细只停留在 Python 内部。
- Milvus 或 Neo4j 不可用时不阻断流程；对应维度标记为 `unavailable`，其正向权重从可用维度中重新归一化。
- 多样性重排在基础综合分之后执行，并保持确定性。
- 离线评估脚本与线上排序模块复用同一套评分和重排逻辑。
- 自动化测试使用本地 fixture 和 mock client，不依赖公网或真实 Milvus/Neo4j。

## 现状与问题

当前 `python-agent/app/agents/filter_agent.py` 使用本地规则生成 `0..1` 分数：

- 有标题加分
- 有 URL 加分
- 正文长度加分
- 命中用户画像关键词加分
- Neo4j 返回 topics 时加 `0.05`
- Milvus 返回 matches 时加 `0.05`
- `score >= 0.5` 且标题存在时保留

现有问题：

- 评分维度混在一个方法里，缺少清晰边界。
- 权重不可配置。
- 只有总分和少量字符串原因，缺少各维度明细。
- Milvus、Neo4j 信号过于粗糙，不能表达相似度或图谱主题权重。
- 结果没有批次级排序和多样性控制。
- 输出契约没有承载推荐原因、拒绝原因、评分明细。
- 离线评估缺失，无法衡量排序质量。
- 当前分数范围为 `0..1`，不满足新需求的 `0..10`。

## 方案对比

### 方案一：独立排序模块 + Filter Agent 调用

新增 `app/recommendation/` 模块，内部包含配置、特征提取、评分、重排和解释生成。Filter Agent 负责收集文章、用户画像、MCP 信号和日志，再调用排序模块生成结果。

优点：

- 评分逻辑可单独测试。
- 离线评估脚本可以复用同一模块。
- Filter Agent 保持编排职责，不继续膨胀。
- 后续可替换为模型排序或 A/B 配置，不影响 workflow。

这是选定方案。

### 方案二：直接扩写 Filter Agent

在现有 `filter_agent.py` 中继续添加所有评分和排序逻辑。短期改动文件少，但会让 Filter Agent 同时承担 MCP 编排、特征提取、打分、重排、解释、配置解析职责，难以测试和维护，因此不采用。

### 方案三：交给外部推荐服务

新增推荐服务，由 Python Agent 调用外部服务获取排序结果。该方案边界清晰，但当前项目还处于本地可验证阶段，引入额外服务会增加部署、观测和失败面，因此不纳入本轮。

## 总体架构

```text
ArticleWorkflow
  -> FilterAgent
     -> 收集本地文章字段
     -> 可选调用 embedding-mcp
     -> 可选调用 milvus-mcp
     -> 可选调用 neo4j-mcp
     -> RecommendationRanker
        -> FeatureExtractor
        -> ScoreCalculator
        -> DiversityReranker
        -> ExplanationBuilder
     -> article_results
  -> SummaryAgent
  -> RewriteAgent
  -> CheckAgent
```

离线评估链路：

```text
evaluation fixture
  -> RecommendationRanker
  -> ranked results
  -> Precision@K / Recall@K / NDCG@K / diversity / duplicate_rate
  -> JSON report
```

## 配置设计

Python 配置新增 `recommendation` 段。默认配置位于代码默认值中，`python-agent/config.yaml` 可以覆盖。

```yaml
recommendation:
  min_keep_score: 5.0
  weights:
    keyword_match: 1.0
    profile_topic: 1.2
    milvus_similarity: 1.0
    neo4j_related_topic: 0.9
    source_quality: 0.8
    freshness: 0.7
    duplicate_penalty: 1.0
    negative_preference_penalty: 1.0
    content_quality: 1.1
  diversity:
    max_same_source_ratio: 0.5
    max_same_topic_ratio: 0.5
    max_consecutive_same_topic: 2
    topic_window_size: 5
  freshness:
    half_life_days: 14
    max_age_days: 90
  source_quality:
    default_score: 6.0
    sources:
      arxiv: 8.0
      github: 7.5
      huggingface: 7.5
      example.com: 5.0
  milvus:
    minimum_score: 0.75
  duplicate:
    same_url_penalty: 10.0
    same_title_penalty: 7.0
    similar_memory_penalty_threshold: 0.92
  negative_preferences:
    penalty_per_match: 2.0
    max_penalty: 6.0
```

配置规则：

- 缺失配置使用默认值。
- 权重小于 0 时按 0 处理。
- 正向维度权重总和为 0 时返回 0 分并拒绝。
- 惩罚维度使用正权重表达惩罚强度，不参与正向分母。
- 所有单维分输出到 `0..10`。
- 最终分裁剪到 `0..10`。

## 评分维度

### 关键词匹配分

来源：

- 用户画像中的 `keywords`、`interests`、`preferred_tags`
- 文章 `title`、`raw_text`、`tags`

规则：

- 命中数量越多分越高。
- 标题和标签命中权重大于正文命中。
- 最多输出 10 分。
- 明细记录命中的关键词。

### 用户画像主题权重

来源：

- 用户画像 `topics`
- 用户画像中可解析的主题权重，例如 JSON 字符串或 `topic:weight` 列表
- 文章标签、标题、正文

规则：

- 主题权重归一化到 `0..1` 后映射到 `0..10`。
- 命中多个主题时取加权平均和最高主题的组合。
- 明细记录命中的主题与权重。

### Milvus 语义相似度

来源：

- embedding-mcp 生成文章向量
- milvus-mcp `search_similar_memory`

规则：

- 读取 matches 中的最高 `score`，按 `0..1` 映射到 `0..10`。
- 如果 Milvus 不可用、未启用或没有 embedding，维度标记为 `unavailable`。
- 如果 matches 为空，维度可用但得分为 0。
- 高相似度既可表示相关兴趣，也可能表示历史重复。是否重复由历史重复惩罚维度单独判断。

### Neo4j 相关主题权重

来源：

- neo4j-mcp `query_user_interest_graph`
- 可选 `get_related_topics`

规则：

- Neo4j 返回字符串主题时，命中文章主题得基础分。
- Neo4j 返回对象主题时，读取 `name` 和 `score`。
- 图谱主题与文章主题直接匹配或相关匹配时加分。
- Neo4j 不可用、未启用或调用失败时标记为 `unavailable`。

### 来源质量分

来源：

- 文章 `source`
- 文章 URL host
- 配置中的 `source_quality.sources`

规则：

- 优先匹配 source，其次匹配 URL host。
- 未配置来源使用 `default_score`。
- 输出裁剪到 `0..10`。

### 内容时效分

来源：

- 文章 `published_at`
- 当前运行时钟

规则：

- 可解析发布时间时，根据半衰期衰减。
- 新内容接近 10 分。
- 超过 `max_age_days` 接近 0 分。
- 缺失或不可解析发布时间时使用中性分 5 分，并在明细记录 `missing_published_at` 或 `invalid_published_at`。

### 历史重复惩罚

来源：

- 文章 URL、标题
- 用户画像中的 `seen_article_ids`、`seen_urls`、`seen_titles`
- Milvus 高相似度 matches

规则：

- 相同 URL 强惩罚。
- 相同标题中等惩罚。
- Milvus similarity 高于重复阈值时惩罚。
- 惩罚维度输出 `0..10`，表示惩罚强度。
- 最终总分中扣除加权惩罚。

### 负面偏好惩罚

来源：

- 用户画像中的 `negative_keywords`、`negative_topics`、`disliked_sources`
- 文章标题、正文、标签、来源

规则：

- 每命中一个负面偏好增加惩罚。
- 惩罚上限由配置控制。
- 明细记录命中的负面偏好。

### 内容质量分

来源：

- 标题是否存在
- URL 是否存在
- 正文长度
- 标签数量
- 文本噪声比例
- fetch_status

规则：

- 有标题、有 URL、正文长度合理、标签存在时加分。
- 正文过短、标题缺失、抓取失败、噪声过高时降分。
- 输出裁剪到 `0..10`。

## 综合分

综合分计算：

```text
positive_score =
  sum(available_positive_dimension_score * dimension_weight)
  / sum(available_positive_dimension_weight)

penalty =
  sum(penalty_dimension_score * penalty_dimension_weight)
  / sum(penalty_dimension_weight)

final_score = clamp(positive_score - penalty, 0, 10)
```

正向维度：

- keyword_match
- profile_topic
- milvus_similarity
- neo4j_related_topic
- source_quality
- freshness
- content_quality

惩罚维度：

- duplicate_penalty
- negative_preference_penalty

保留规则：

- `final_score >= min_keep_score`
- 标题存在
- 内容质量分不为 0
- 没有命中硬拒绝原因

硬拒绝原因：

- 缺少 `article_id`
- 缺少标题
- 缺少正文且缺少 URL
- 负面偏好惩罚达到 10
- 历史重复惩罚达到 10

## 多样性重排

基础排序：

1. `keep=true` 优先于 `keep=false`
2. `score` 降序
3. `article_id` 升序

多样性重排只在 `keep=true` 的候选集中执行。

约束：

- 同一来源占比不超过 `max_same_source_ratio`，除非候选集不足。
- 同一主题占比不超过 `max_same_topic_ratio`，除非候选集不足。
- 同一主题最多连续出现 `max_consecutive_same_topic` 篇。
- 主题窗口内优先选择未出现或出现较少的主题。

主题识别优先级：

1. 文章 tags
2. 命中的用户画像主题
3. Neo4j 命中的相关主题
4. 来源名
5. `unknown`

确定性要求：

- 不使用随机数。
- 所有候选排序的 tie-breaker 使用 `article_id`、`source`、`title` 的稳定字符串顺序。
- 相同输入、相同配置、相同 MCP mock 返回必须得到相同排序。

## 输出契约

Python 内部 `article_results` 新增字段：

```json
{
  "article_id": "a1",
  "keep": true,
  "score": 8.24,
  "rank_position": 1,
  "score_breakdown": [
    {
      "dimension": "keyword_match",
      "available": true,
      "raw_score": 7.0,
      "normalized_score": 7.0,
      "weight": 1.0,
      "contribution": 0.91,
      "evidence": ["AI", "workflow"]
    }
  ],
  "recommendation_reasons": [
    "命中用户关键词：AI, workflow",
    "内容质量较高"
  ],
  "rejection_reasons": []
}
```

protobuf 扩展：

- 新增 `ScoreBreakdownItem`
- `ArticleProcessResult` 新增：
  - `repeated ScoreBreakdownItem score_breakdown = 9`
  - `repeated string recommendation_reasons = 10`
  - `repeated string rejection_reasons = 11`
  - `int32 rank_position = 12`

兼容性：

- 现有字段编号不变。
- 新字段只追加，不删除旧字段。
- GoFrame 未使用新字段时仍可正常处理旧逻辑。
- Python gRPC 响应必须填充新字段。

## GoFrame 接入

GoFrame 本轮最小接入：

- 重新生成 `agentpb`。
- `proto_contract_test` 增加新字段断言。
- `persistAgentResults` 可继续只依赖 `keep/post_text/check_pass` 保存 posts。
- run log metadata 可追加推荐统计：
  - `kept_count`
  - `rejected_count`
  - `top_score`
  - `diversity_topics`

不在本轮新增数据库表。评分明细通过 gRPC 可见，后续如需要长期留存，再单独设计 `recommendation_scores` 表。

## 离线评估脚本

新增脚本：

```text
python-agent/scripts/evaluate_recommendations.py
```

输入 JSON 或 JSONL：

```json
{
  "user_profile_snapshot": {
    "interests": "AI,knowledge-management",
    "negative_keywords": "crypto"
  },
  "articles": [
    {
      "article_id": "a1",
      "title": "AI workflow",
      "raw_text": "Agent workflow details...",
      "source": "arxiv",
      "published_at": "2026-06-01T00:00:00Z",
      "tags": ["AI"],
      "label": 1,
      "relevance": 3
    }
  ],
  "k": 5
}
```

输出 JSON：

```json
{
  "k": 5,
  "precision_at_k": 0.8,
  "recall_at_k": 0.67,
  "ndcg_at_k": 0.91,
  "diversity": 0.6,
  "duplicate_rate": 0.1,
  "items_evaluated": 20
}
```

指标定义：

- `Precision@K`：Top K 中 label 为正的比例。
- `Recall@K`：Top K 命中的正样本数 / 全部正样本数。
- `NDCG@K`：使用 `relevance` 计算 DCG，并除以理想 DCG。
- `diversity`：Top K 中不同主题数 / Top K 数。
- `duplicate_rate`：Top K 中重复 URL、重复标题或重复 article_id 的比例。

脚本要求：

- 默认 `K=5`。
- 支持 `--k`、`--input`、`--output`。
- 不调用真实 MCP。
- 可使用 fixture 中的 `milvus_matches`、`neo4j_topics` 模拟外部信号。
- 相同输入必须输出相同报告。

## 测试策略

Python 单元测试：

- 权重配置影响综合分。
- 9 个维度都输出明细。
- 分数裁剪到 `0..10`。
- 最低保留分数生效。
- 推荐原因和拒绝原因生效。
- 同来源和同主题多样性约束生效。
- Milvus 缺失时降级评分。
- Neo4j 缺失时降级评分。
- 相同输入重复运行排序一致。
- 离线评估指标计算正确。

gRPC 测试：

- `ArticleWorkflow.process_articles` 返回新解释字段。
- `AgentService.ProcessArticles` 把新字段写入 protobuf。
- 旧的 `summary/rewrite/check` 流程仍能处理保留文章。

Go 测试：

- proto contract 包含新字段。
- Go protobuf 生成代码可编译。
- harness 在新字段存在时仍可保存 posts 和 MCP logs。

验证命令：

```powershell
cd python-agent
python -m pytest tests -q
cd ..\goframe-backend
go test ./... -count=1
```

## 非目标

本轮不做：

- 新增推荐分数数据库表。
- 引入在线学习模型。
- 接入真实点击流训练。
- 改造前端展示页面。
- 强依赖真实 Milvus、Neo4j 或公网数据。
- 修改 SummaryAgent、RewriteAgent、CheckAgent 的核心逻辑。

## 风险与处理

- 风险：`score` 从 `0..1` 变成 `0..10` 可能影响下游理解。
  - 处理：文档、测试和 proto 注释同步更新，并保留字段名不变。
- 风险：protobuf 生成代码涉及 Go/Python 两侧，容易漏同步。
  - 处理：proto contract test 和 Python gRPC 测试同时覆盖。
- 风险：多样性重排降低部分高分文章排名。
  - 处理：只在 `keep=true` 候选中重排，并保留原始综合分和排名解释。
- 风险：MCP 失败导致权重变化不透明。
  - 处理：明细中标记 `available=false`，原因写入 evidence 和 rejection/recommendation reasons。
- 风险：用户画像字段格式不统一。
  - 处理：解析器兼容字符串、列表、JSON 对象和 `topic:weight` 文本。

## 自检结论

- 需求中的 9 个评分维度均已覆盖。
- 每个维度可配置权重。
- 综合分定义为 `0..10`。
- 输出包含维度明细、推荐原因和拒绝原因。
- 最低保留分数、多样性约束、主题分散、Milvus/Neo4j 降级、确定性排序均有设计。
- 离线评估脚本覆盖 Precision@K、Recall@K、NDCG@K、多样性、重复率。
- 未包含占位项或未定义的后续步骤。
