# 个性化推荐排序实施计划

> 原文镜像：`docs/superpowers/plans/2026-06-08-personalized-recommendation-ranking.md`
>
> 本文件为中文结构化译本。原文中的大段测试代码、命令和生成代码说明以原文件为准；本译本保留完整任务路线、文件范围、步骤顺序和验收意图。

> **给 agentic workers：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施本计划。步骤使用 checkbox（`- [ ]`）语法追踪。

**目标：** 将 Python Filter Agent 升级为可解释、可配置、可降级、可重复测试的个性化推荐排序系统，并补齐 gRPC 输出和离线评估能力。

**架构：** 新增 `app/recommendation/` 作为独立排序模块，Filter Agent 只负责收集本地文章字段与 MCP 信号并调用排序器。排序器输出 0 到 10 综合分、维度明细、推荐/拒绝原因和稳定排名；protobuf/gRPC 追加解释字段，GoFrame 最小接入保持 posts 落库逻辑不变。

**技术栈：** Python 3.10+、unittest/pytest、protobuf/gRPC、Go 1.x、PowerShell 验证脚本。

## 文件结构

- 新建 `python-agent/app/recommendation/__init__.py`：导出推荐配置、排序器和评估函数。
- 新建 `python-agent/app/recommendation/config.py`：定义 `RecommendationSettings`、默认权重、多样性和时效配置。
- 新建 `python-agent/app/recommendation/ranker.py`：实现评分维度、综合分、推荐/拒绝原因、多样性重排。
- 新建 `python-agent/app/recommendation/evaluation.py`：实现 Precision@K、Recall@K、NDCG@K、多样性、重复率。
- 新建 `python-agent/scripts/evaluate_recommendations.py`：离线评估 CLI。
- 新建 `python-agent/tests/test_recommendation_ranker.py` 与 `test_recommendation_evaluation.py`。
- 修改 `python-agent/app/config.py` 与 `python-agent/config.yaml`，加载默认推荐排序配置。
- 修改 `python-agent/app/agents/filter_agent.py`，接入新排序器，替换旧 `_score_article` 主路径。
- 修改 workflow、gRPC server、proto、生成文件和契约测试，透传评分明细、原因和排名。
- 修改 `python-agent/app/skills/filter_skill.md` 和 `README.md`，记录新输出、离线评估命令和 proto 生成提示。

## Task 1：Recommendation Configuration

**文件：** recommendation config、`app/config.py`、`config.yaml`、ranker tests

- [ ] 编写失败的配置测试，验证默认权重、阈值、多样性、时效配置和配置覆盖。
- [ ] 运行测试确认失败。
- [ ] 实现 `RecommendationSettings`、默认值和 YAML 加载。
- [ ] 运行测试确认通过。

## Task 2：Core Ranker Scoring

**文件：** `ranker.py`、`test_recommendation_ranker.py`

- [ ] 编写失败的 ranker 测试，覆盖关键词、画像主题、Milvus 相似度、Neo4j 相关主题、来源质量、时效、重复惩罚、负面偏好惩罚和内容质量。
- [ ] 运行测试确认失败。
- [ ] 实现排序数据结构和评分逻辑，输出 0 到 10 综合分、逐维 `score_breakdown`、推荐/拒绝原因和稳定排名。
- [ ] 运行 ranker 测试确认通过。

## Task 3：Filter Agent Integration

**文件：** `filter_agent.py`、workflow state/graph、workflow tests

- [ ] 编写 workflow 失败测试，要求 Filter Agent 输出新的解释字段。
- [ ] 运行测试确认失败。
- [ ] 将 recommendation settings 注入 `FilterAgent`。
- [ ] 用 batch ranking 替换逐文章简单评分主路径。
- [ ] 在 workflow 输出中透传新字段。
- [ ] 运行 workflow 测试。

## Task 4：Protobuf 与 gRPC 解释字段

**文件：** `shared/proto/agent.proto`、`proto/agent.proto`、生成文件、gRPC server、契约测试

- [ ] 编写失败的 proto contract tests。
- [ ] 运行契约测试确认失败。
- [ ] 扩展 proto 文件，新增 `ScoreBreakdownItem` 和 `ArticleProcessResult` 追加字段。
- [ ] 重新生成 Python protobuf stubs。
- [ ] 重新生成 Go protobuf stubs。
- [ ] 映射 gRPC response fields。
- [ ] 增加 protobuf service assertion。
- [ ] 运行 proto 和 workflow 测试。

## Task 5：Diversity Constraints

**文件：** ranker 和 ranker tests

- [ ] 编写失败的多样性测试。
- [ ] 如果当前简单多样性不足，运行测试确认失败。
- [ ] 实现 window-aware diversity，避免结果过度集中在同一来源或主题。
- [ ] 运行 ranker 测试。

## Task 6：Offline Evaluation Metrics 与 CLI

**文件：** `evaluation.py`、`evaluate_recommendations.py`、evaluation tests

- [ ] 编写失败的指标测试，覆盖 Precision@K、Recall@K、NDCG@K、多样性和重复率。
- [ ] 运行测试确认失败。
- [ ] 实现 evaluation functions。
- [ ] 实现 CLI，读取离线评估 JSON 并输出指标。
- [ ] 运行 evaluation 测试。

## Task 7：Filter Skill 与 README 更新

**文件：** `filter_skill.md`、`README.md`

- [ ] 如需要，编写文档期望失败测试。
- [ ] 更新 Filter skill 输出示例，将简单分更新为 0 到 10 的可解释推荐分。
- [ ] 更新 README，记录推荐排序配置、离线评估命令和输出字段。
- [ ] 运行 skill/documentation 相关测试。

## Task 8：最终验证

- [ ] 运行 Python recommendation tests。
- [ ] 运行 Python workflow tests。
- [ ] 运行 proto contract checks。
- [ ] 运行 Go tests。
- [ ] 审查 git diff，不暂存无关文件。

## 自检

- 推荐排序可解释、可配置、可降级。
- MCP 不可用时仍能基于本地规则输出结构化结果。
- 排序稳定可复测，同分处理确定。
- gRPC 与 proto 字段只追加，不破坏兼容。
- 离线评估 CLI 可用于回归推荐质量。
