"""fact_node 流程中使用的中间数据结构。

这些 dataclass 用于 LLM 输出解析和 pipeline 阶段传参，
不是 Neo4j 的真实节点 schema。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Literal

# 与 ENTITY_PROMPT 中允许输出的 entity_type 保持一致。
# EntityType = Literal["人物", "地点", "组织", "时间",  "对象"]
# ALLOWED_ENTITY_TYPES = {"人物", "地点", "组织", "时间",  "对象"}
EntityType = Literal["Person", "Location", "Organization", "Object",  "Time"]
ALLOWED_ENTITY_TYPES = {"Person", "Location", "Organization", "Object",  "Time"}

@dataclass
class DerivedFactCandidate:
    """阶段 1 生成的派生事实候选。
    summary: 弱推断得到的派生结论。
    """
    summary: str = ""



@dataclass
class OriginalFactCandidate:
    """阶段 1 生成的原始事实候选。
    content: chunk summary 原文。
    summary: LLM 生成或合并后的 topic。
    derived_facts: profile_update=1 时生成的派生候选。
    source_summary_index: 对应 summary 列表中的下标。
    """
    content: str = ""
    summary: str = ""
    derived_facts: List[DerivedFactCandidate] = field(default_factory=list)
    source_summary_index: int = 0


@dataclass
class EntityItem:
    """ENTITY_PROMPT 解析后的实体候选。"""
    name: str
    type: EntityType
    semantic: str = ""


@dataclass
class ProfileUpdateDecision:
    """画像更新决策。

    should_update 控制是否写画像；updates 只放需要更新的字段。
    """
    should_update: bool = False
    updates: Dict[str, str] = field(default_factory=dict)
    reason: str = ""


@dataclass
class ExtractResult:
    """阶段 1 的统一输出，供后续 OriginalFact / Entity / DerivedFact 阶段消费。"""
    original_facts: List[OriginalFactCandidate] = field(default_factory=list)
    entities: List[EntityItem] = field(default_factory=list)
   