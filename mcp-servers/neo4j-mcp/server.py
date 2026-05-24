# 文件作用：
# 本文件实现 neo4j-mcp 服务，负责用户兴趣图谱的查询、更新、相关主题检索和推荐解释。
# 当前实现使用进程内 USER_GRAPH 做 mock 图谱，不连接真实 Neo4j；配置中保留了 neo4j_uri 和 database。
#
# 在项目中的位置：
# 本文件属于 MCP Server 层，被 Python Agent 的 Neo4jClient 通过 JSON-RPC 调用。
#
# 主要内容：
# 1. CONFIG：读取 mock 和 Neo4j 预留配置。
# 2. USER_GRAPH：进程内模拟用户兴趣图谱。
# 3. TOOLS：声明 query_user_interest_graph、update_user_interest_graph、get_related_topics、explain_recommendation。
# 4. ALIASES：兼容旧工具名。
# 5. handle 和各 _xxx 函数：执行图谱查询、更新和解释。
#
# 关键调用关系：
# - FilterAgent 调用 query_user_interest_graph 读取用户兴趣上下文。
# - MemoryAgent 调用 update_user_interest_graph 根据反馈更新画像/图谱。
#
# 初学者阅读建议：
# 注意这里的图谱是 mock map，不是真实 Neo4j；真实服务需要把这些函数替换为 Neo4j driver 查询。
from __future__ import annotations

import os
from pathlib import Path
import sys

# 将公共 MCP 框架加入导入路径。
sys.path.append(str(Path(__file__).resolve().parents[1] / "common"))

from simple_http_mcp import ToolError, ToolSpec, require_object, require_str, run_server  # noqa: E402


# CONFIG 保存 mock 状态和真实 Neo4j 预留连接配置。
CONFIG = {
    "mock_mode": os.getenv("NEO4J_MOCK_MODE", "true").lower() != "false",
    "neo4j_uri": os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
    "neo4j_database": os.getenv("NEO4J_DATABASE", "neo4j"),
}

# USER_GRAPH 是 mock 用户兴趣图谱。
# key 是 user_id，value 是 topic -> weight 的映射。
USER_GRAPH: dict[str, dict[str, float]] = {
    "default-user": {"AI": 0.91, "knowledge-management": 0.84, "engineering": 0.72}
}

# TOOLS 声明 neo4j-mcp 对外暴露的工具。
TOOLS = [
    # 查询用户兴趣图谱。
    ToolSpec(
        name="query_user_interest_graph",
        description="Read a mock user interest graph.",
        input_schema={"type": "object", "required": ["user_id"], "properties": {"user_id": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"user_id": {"type": "string"}, "topics": {"type": "array"}}},
        examples=[{"request": {"user_id": "default-user"}, "response": {"topics": [{"name": "AI", "weight": 0.91}]}}],
    ),
    # 根据反馈信号更新用户兴趣图谱。
    ToolSpec(
        name="update_user_interest_graph",
        description="Update mock user interest weights from feedback signals.",
        input_schema={"type": "object", "required": ["user_id", "topics"], "properties": {"user_id": {"type": "string"}, "topics": {"type": "array"}}},
        output_schema={"type": "object", "properties": {"updated": {"type": "boolean"}, "topics": {"type": "array"}}},
        examples=[{"request": {"user_id": "default-user", "topics": [{"name": "AI", "weight": 0.1}]}, "response": {"updated": True}}],
    ),
    # 查询相关主题。
    ToolSpec(
        name="get_related_topics",
        description="Return mock related topics for one seed topic.",
        input_schema={"type": "object", "required": ["topic"], "properties": {"topic": {"type": "string"}, "limit": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {"topics": {"type": "array"}}},
        examples=[{"request": {"topic": "AI"}, "response": {"topics": [{"name": "agents", "score": 0.86}]}}],
    ),
    # 解释推荐原因。
    ToolSpec(
        name="explain_recommendation",
        description="Explain why an article matches the mock user graph.",
        input_schema={"type": "object", "required": ["user_id", "article"], "properties": {"user_id": {"type": "string"}, "article": {"type": "object"}}},
        output_schema={"type": "object", "properties": {"reasons": {"type": "array"}, "score": {"type": "number"}}},
        examples=[{"request": {"user_id": "default-user", "article": {"title": "AI workflow"}}, "response": {"score": 0.91}}],
    ),
]


# ALIASES 兼容 Python Agent 旧版工具名。
# 例如 Neo4jClient.update_profile 早期可能调用 update_profile，实际转为 update_user_interest_graph。
ALIASES = {
    "query_profile_context": "query_user_interest_graph",
    "update_profile": "update_user_interest_graph",
}


# 函数作用：
# MCP 工具分发入口。
#
# 参数说明：
# - tool：工具名。
# - payload：工具参数。
#
# 返回值：
# - 返回工具输出字典。
def handle(tool: str, payload: dict[str, object]) -> dict[str, object]:
    # 先处理别名，保证旧工具名仍能调用当前实现。
    tool = ALIASES.get(tool, tool)
    # 查询兴趣图谱。
    if tool == "query_user_interest_graph":
        return _query_user_interest_graph(payload)
    # 更新兴趣图谱。
    if tool == "update_user_interest_graph":
        return _update_user_interest_graph(payload)
    # 查询相关主题。
    if tool == "get_related_topics":
        return _get_related_topics(payload)
    # 解释推荐原因。
    if tool == "explain_recommendation":
        return _explain_recommendation(payload)
    raise ToolError(f"unknown tool `{tool}`", code=-32601)


# 函数作用：
# 查询用户兴趣图谱上下文。
def _query_user_interest_graph(payload: dict[str, object]) -> dict[str, object]:
    # user_id 缺失时使用 default-user。
    user_id = require_str(payload, "user_id", "default-user") or "default-user"
    # snapshot 可把 GoFrame 传来的 user_profile_snapshot 合并进 mock 图谱。
    snapshot = payload.get("snapshot", {})
    if isinstance(snapshot, dict):
        _merge_snapshot(user_id, snapshot)
    # 按权重返回主题列表。
    topics = _topics(user_id)
    return {"user_id": user_id, "topics": topics, "mock": CONFIG["mock_mode"]}


# 函数作用：
# 根据用户画像快照、显式 topics 或 extracted_feedback 更新 mock 兴趣图谱。
def _update_user_interest_graph(payload: dict[str, object]) -> dict[str, object]:
    # user_id 缺失时使用 default-user。
    user_id = str(payload.get("user_id") or "default-user")
    # 如果 payload 中包含 snapshot，就先把其中 interests 合并进图谱。
    if "snapshot" in payload:
        snapshot = require_object(payload, "snapshot")
        _merge_snapshot(user_id, snapshot)
    # 如果 payload 显式传 topics，就按权重增量更新。
    for topic in payload.get("topics", []) if isinstance(payload.get("topics", []), list) else []:
        if isinstance(topic, dict):
            name = str(topic.get("name", "")).strip()
            weight = float(topic.get("weight", 0.1) or 0.1)
            if name:
                # 权重限制在 0..1，避免无限增长。
                USER_GRAPH.setdefault(user_id, {})[name] = min(1.0, max(0.0, USER_GRAPH.setdefault(user_id, {}).get(name, 0.0) + weight))
    # 从反馈文本中识别候选主题，并小幅提高权重。
    for feedback in payload.get("extracted_feedback", []) if isinstance(payload.get("extracted_feedback", []), list) else []:
        text = str(feedback)
        for candidate in ["AI", "knowledge-management", "engineering", "workflow", "summary"]:
            if candidate.lower() in text.lower():
                USER_GRAPH.setdefault(user_id, {})[candidate] = min(1.0, USER_GRAPH.setdefault(user_id, {}).get(candidate, 0.4) + 0.05)
    return {"updated": True, "user_id": user_id, "topics": _topics(user_id), "mock": CONFIG["mock_mode"]}


# 函数作用：
# 返回某个主题的相关主题列表。
def _get_related_topics(payload: dict[str, object]) -> dict[str, object]:
    # topic 是必填字符串。
    topic = require_str(payload, "topic")
    # limit 限制在 1..20。
    limit = max(1, min(int(payload.get("limit", 5) or 5), 20))
    # related_map 是 mock 主题关系。
    related_map = {
        "AI": ["agents", "LLM", "workflow", "evaluation", "retrieval"],
        "knowledge-management": ["PKM", "graph", "memory", "summarization", "taxonomy"],
        "engineering": ["testing", "observability", "architecture", "automation", "reliability"],
    }
    # 未知主题返回通用相关主题。
    related = related_map.get(topic, ["AI", "knowledge-management", "engineering", "workflow", "memory"])
    return {"topic": topic, "topics": [{"name": name, "score": round(0.9 - idx * 0.06, 4)} for idx, name in enumerate(related[:limit])], "mock": CONFIG["mock_mode"]}


# 函数作用：
# 根据用户图谱解释一篇文章的推荐原因。
def _explain_recommendation(payload: dict[str, object]) -> dict[str, object]:
    # 读取 user_id 和 article。
    user_id = require_str(payload, "user_id", "default-user") or "default-user"
    article = require_object(payload, "article")
    # 将标题、摘要和正文拼在一起做简单关键词匹配。
    text = f"{article.get('title', '')} {article.get('summary', '')} {article.get('raw_text', '')}".lower()
    reasons = []
    score = 0.0
    # 遍历用户图谱主题，命中文本时生成解释。
    for topic, weight in USER_GRAPH.get(user_id, USER_GRAPH["default-user"]).items():
        if topic.lower() in text:
            reasons.append(f"matched user topic `{topic}`")
            score = max(score, weight)
    # 没有命中时返回基线解释。
    if not reasons:
        reasons.append("no direct topic match; returned baseline recommendation")
        score = 0.35
    return {"user_id": user_id, "score": round(score, 4), "reasons": reasons, "mock": CONFIG["mock_mode"]}


# 函数作用：
# 将 user_profile_snapshot 中的 interests 合并进 mock 图谱。
def _merge_snapshot(user_id: str, snapshot: dict[str, object]) -> None:
    # interests 支持逗号或分号分隔。
    interests = str(snapshot.get("interests", ""))
    for raw in interests.replace(";", ",").split(","):
        topic = raw.strip()
        if topic:
            # 快照中的兴趣至少给 0.7 权重。
            USER_GRAPH.setdefault(user_id, {})[topic] = max(USER_GRAPH.setdefault(user_id, {}).get(topic, 0.0), 0.7)


# 函数作用：
# 返回某个用户按权重降序排列的主题列表。
def _topics(user_id: str) -> list[dict[str, object]]:
    # 如果用户不存在，就复制 default-user 的初始主题。
    graph = USER_GRAPH.setdefault(user_id, dict(USER_GRAPH["default-user"]))
    return [{"name": name, "weight": round(weight, 4)} for name, weight in sorted(graph.items(), key=lambda item: item[1], reverse=True)]


# 直接运行本文件时启动 neo4j-mcp。
if __name__ == "__main__":
    run_server("neo4j-mcp", int(os.getenv("PORT", "7004")), TOOLS, handle, CONFIG)
