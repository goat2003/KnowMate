# 中文文档索引

本目录提供项目自维护 Markdown 文档的中文入口。为了遵守“保留原项目内容和代码”的要求，本次没有覆盖根目录或各模块下的原始 `.md` 文件，而是在 `docs/zh-CN/` 下新增中文镜像。

## 范围说明

已纳入项目自维护文档：

- 根目录 README、架构、安全、运维、发布检查清单、已知限制、下一版本规划。
- `shared/config` 配置说明。
- `mcp-servers` 及各子 MCP server README。
- `python-agent/app/skills` 下的 Agent skill 说明。
- `docs/` 下的调用链、函数精读、学习笔记、可观测性、实施计划和设计文档。

未纳入翻译范围：

- `node_modules`、`.pytest_cache` 等依赖或缓存目录。
- `shared/outputs` 和 `goframe-backend/internal/logic/harness/test-output` 等运行/测试生成产物。
- 非 Markdown 的代码、配置、SQL、proto 和脚本。

## 镜像规则

- 英文较多的 README、MCP 文档和计划/设计稿提供中文译本或中文结构化译本。
- 原文件已经中文为主的文档，镜像会保留原文，并追加“原文镜像”说明，方便中文入口统一。
- 命令、路径、环境变量、协议字段、表名和代码块保持原样，便于与原文对照。

## 根目录文档

| 原始文档 | 中文镜像 |
| --- | --- |
| `README.md` | `docs/zh-CN/README.md` |
| `ARCHITECTURE.md` | `docs/zh-CN/ARCHITECTURE.md` |
| `OPERATIONS.md` | `docs/zh-CN/OPERATIONS.md` |
| `SECURITY.md` | `docs/zh-CN/SECURITY.md` |
| `RELEASE_CHECKLIST.md` | `docs/zh-CN/RELEASE_CHECKLIST.md` |
| `NEXT_VERSION_PLAN.md` | `docs/zh-CN/NEXT_VERSION_PLAN.md` |
| `KNOWN_LIMITATIONS.md` | `docs/zh-CN/KNOWN_LIMITATIONS.md` |

## 模块 README

| 原始文档 | 中文镜像 |
| --- | --- |
| `shared/config/README.md` | `docs/zh-CN/shared/config/README.md` |
| `mcp-servers/README.md` | `docs/zh-CN/mcp-servers/README.md` |
| `mcp-servers/fetch-mcp/README.md` | `docs/zh-CN/mcp-servers/fetch-mcp/README.md` |
| `mcp-servers/embedding-mcp/README.md` | `docs/zh-CN/mcp-servers/embedding-mcp/README.md` |
| `mcp-servers/milvus-mcp/README.md` | `docs/zh-CN/mcp-servers/milvus-mcp/README.md` |
| `mcp-servers/neo4j-mcp/README.md` | `docs/zh-CN/mcp-servers/neo4j-mcp/README.md` |

## Python Agent Skills

| 原始文档 | 中文镜像 |
| --- | --- |
| `python-agent/app/skills/filter_skill.md` | `docs/zh-CN/python-agent/app/skills/filter_skill.md` |
| `python-agent/app/skills/summary_skill.md` | `docs/zh-CN/python-agent/app/skills/summary_skill.md` |
| `python-agent/app/skills/rewrite_post_skill.md` | `docs/zh-CN/python-agent/app/skills/rewrite_post_skill.md` |
| `python-agent/app/skills/fact_check_skill.md` | `docs/zh-CN/python-agent/app/skills/fact_check_skill.md` |
| `python-agent/app/skills/feedback_extract_skill.md` | `docs/zh-CN/python-agent/app/skills/feedback_extract_skill.md` |
| `python-agent/app/skills/memory_update_skill.md` | `docs/zh-CN/python-agent/app/skills/memory_update_skill.md` |
| `python-agent/app/skills/mcp_tool_usage_skill.md` | `docs/zh-CN/python-agent/app/skills/mcp_tool_usage_skill.md` |

## Docs

| 原始文档 | 中文镜像 |
| --- | --- |
| `docs/function_reading.md` | `docs/zh-CN/docs/function_reading.md` |
| `docs/call_chain.md` | `docs/zh-CN/docs/call_chain.md` |
| `docs/learning_notes.md` | `docs/zh-CN/docs/learning_notes.md` |
| `docs/observability.md` | `docs/zh-CN/docs/observability.md` |

## Superpowers Plans

| 原始文档 | 中文镜像 |
| --- | --- |
| `docs/superpowers/plans/2026-06-05-standard-mcp-upgrade.md` | `docs/zh-CN/docs/superpowers/plans/2026-06-05-standard-mcp-upgrade.md` |
| `docs/superpowers/plans/2026-06-06-production-memory-providers.md` | `docs/zh-CN/docs/superpowers/plans/2026-06-06-production-memory-providers.md` |
| `docs/superpowers/plans/2026-06-06-production-crawler-content-processing.md` | `docs/zh-CN/docs/superpowers/plans/2026-06-06-production-crawler-content-processing.md` |
| `docs/superpowers/plans/2026-06-08-feedback-memory-profile-versioning.md` | `docs/zh-CN/docs/superpowers/plans/2026-06-08-feedback-memory-profile-versioning.md` |
| `docs/superpowers/plans/2026-06-08-personalized-recommendation-ranking.md` | `docs/zh-CN/docs/superpowers/plans/2026-06-08-personalized-recommendation-ranking.md` |
| `docs/superpowers/plans/2026-06-08-unified-observability.md` | `docs/zh-CN/docs/superpowers/plans/2026-06-08-unified-observability.md` |
| `docs/superpowers/plans/2026-06-09-production-candidate-acceptance.md` | `docs/zh-CN/docs/superpowers/plans/2026-06-09-production-candidate-acceptance.md` |
| `docs/superpowers/plans/2026-06-09-web-admin.md` | `docs/zh-CN/docs/superpowers/plans/2026-06-09-web-admin.md` |

## Superpowers Specs

| 原始文档 | 中文镜像 |
| --- | --- |
| `docs/superpowers/specs/2026-06-06-production-memory-providers-design.md` | `docs/zh-CN/docs/superpowers/specs/2026-06-06-production-memory-providers-design.md` |
| `docs/superpowers/specs/2026-06-06-production-crawler-content-processing-design.md` | `docs/zh-CN/docs/superpowers/specs/2026-06-06-production-crawler-content-processing-design.md` |
| `docs/superpowers/specs/2026-06-08-feedback-memory-profile-versioning-design.md` | `docs/zh-CN/docs/superpowers/specs/2026-06-08-feedback-memory-profile-versioning-design.md` |
| `docs/superpowers/specs/2026-06-08-personalized-recommendation-ranking-design.md` | `docs/zh-CN/docs/superpowers/specs/2026-06-08-personalized-recommendation-ranking-design.md` |
| `docs/superpowers/specs/2026-06-08-unified-observability-design.md` | `docs/zh-CN/docs/superpowers/specs/2026-06-08-unified-observability-design.md` |
