# 文件作用：
# 本文件定义 Python Agent Service 内部通用的数据契约辅助函数。
# 这些函数用于生成 run_id、合并 MCP 默认策略、标准化文章字段。
#
# 在项目中的位置：
# 本文件属于 Python Agent Service 的通用契约层，被 workflow、agents、grpc_server 等模块使用。
#
# 主要内容：
# 1. JsonDict：统一表示 JSON 风格字典的类型别名。
# 2. ensure_run_id：确保每次任务都有 run_id。
# 3. default_mcp_policy：合并 MCP 策略默认值。
# 4. normalize_article：把不同来源文章转换为统一字段结构。
#
# 关键调用关系：
# - ArticleWorkflow.process_articles 调用 ensure_run_id、default_mcp_policy、normalize_article。
# - ArticleWorkflow.process_feedback 调用 ensure_run_id、default_mcp_policy。
#
# 初学者阅读建议：
# 先看 normalize_article 输出了哪些字段，再对照 FilterAgent 如何读取这些字段。
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


# JsonDict 是项目中 JSON 风格 dict 的统一类型别名。
# dict[str, Any] 表示 key 是字符串，value 可以是任意 JSON 可表达或内部对象。
JsonDict = dict[str, Any]


# 函数作用：
# 确保任务拥有 run_id。
#
# 参数说明：
# - value：调用方传入的 run_id，可能为空。
#
# 返回值：
# - 如果 value 非空，原样返回；否则生成 run-时间戳-随机后缀 格式的 id。
#
# 调用关系：
# - 被 ArticleWorkflow.process_articles 和 process_feedback 调用。
def ensure_run_id(value: str | None) -> str:
    # 如果 GoFrame 已经生成 run_id，就沿用它，保证跨服务日志可以关联。
    if value:
        return value
    # 使用 UTC 时间戳作为前缀，便于按时间粗略排序。
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    # uuid4().hex[:8] 提供短随机后缀，降低同一秒内任务 id 冲突概率。
    return f"run-{stamp}-{uuid4().hex[:8]}"


# 函数作用：
# 合并 MCP 策略默认值和请求传入策略。
#
# 参数说明：
# - policy：请求中传入的 MCP 策略字典，可以为空。
#
# 返回值：
# - 返回包含 mock_transport、enable_embedding、enable_fetch、enable_milvus、enable_neo4j 的策略字典。
#
# 调用关系：
# - 被 ArticleWorkflow 构造 state 时调用。
def default_mcp_policy(policy: JsonDict | None = None) -> JsonDict:
    # policy 为空时用 {}，避免后续 current.get 报错。
    current = policy or {}
    # 判断调用方是否显式设置过任一 enable_* 开关。
    # 当前逻辑无论是否显式设置都会返回 merged，但保留这个变量便于未来区分“未传”和“传了 false”。
    has_explicit_enable = any(
        bool(current.get(key))
        for key in ["enable_embedding", "enable_fetch", "enable_milvus", "enable_neo4j"]
    )
    # 默认策略：启用 embedding/milvus/neo4j，禁用 fetch，mock_transport 默认为 True。
    defaults = {
        "mock_transport": True,
        "enable_embedding": True,
        "enable_fetch": False,
        "enable_milvus": True,
        "enable_neo4j": True,
    }
    # Python 3.9+ 的 | 合并字典；current 中同名字段会覆盖 defaults。
    merged = defaults | current
    # 如果调用方传了 enable_*，返回合并结果。
    if has_explicit_enable:
        return merged
    # 当前未传 enable_* 时也返回默认合并结果，保持行为统一。
    return merged


# 函数作用：
# 标准化单篇文章字段。
#
# 参数说明：
# - article：调用方传入的文章字典，可能字段名不完全统一。
#
# 返回值：
# - 返回包含 article_id、url、title、raw_text、source、published_at、tags 的字典。
#
# 调用关系：
# - 被 ArticleWorkflow.process_articles 调用。
# - 输出结果会被 FilterAgent、SummaryAgent、RewriteAgent 继续使用。
def normalize_article(article: JsonDict) -> JsonDict:
    # article_id 按优先级选择：显式 article_id、id、url、title，最后生成随机 id。
    article_id = (
        article.get("article_id")
        or article.get("id")
        or article.get("url")
        or article.get("title")
        or f"article-{uuid4().hex[:8]}"
    )
    # 返回统一字段结构，所有值尽量转换成字符串或列表，便于 protobuf 和 JSON 序列化。
    return {
        # article_id 是文章在结果、数据库和日志中的核心标识。
        "article_id": str(article_id),
        # url 是原文链接，CheckAgent 会检查它是否存在。
        "url": str(article.get("url", "")),
        # title 是筛选和输出中的重要字段。
        "title": str(article.get("title", "")),
        # raw_text 优先使用 raw_text，其次兼容 content 字段。
        "raw_text": str(article.get("raw_text") or article.get("content") or ""),
        # source 表示文章来源，例如 RSS 源名称。
        "source": str(article.get("source", "")),
        # published_at 保存发布时间字符串，不在 Python Agent 中做时间解析。
        "published_at": str(article.get("published_at", "")),
        # tags 转成 list，确保后续处理不会拿到 tuple 或其他可迭代对象。
        "tags": list(article.get("tags", [])),
    }
