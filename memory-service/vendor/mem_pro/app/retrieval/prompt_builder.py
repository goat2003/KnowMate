"""English prompt context builder for retrieval results."""

from __future__ import annotations

from typing import Iterable, List, Optional

from app.retrieval.english_presentation import EnglishPresenter, Translator
from app.retrieval.models import EvidenceItem, json_safe


class PromptBuilder:
    def __init__(self, translator: Optional[Translator] = None) -> None:
        self.presenter = EnglishPresenter(translator=translator)

    def build(
        self,
        query_text: str,
        sub_queries: List[dict],
        evidence_items: Iterable[EvidenceItem],
        max_items: int = 12,
        user_profile: str = "",
    ) -> str:
        selected = list(evidence_items)[:max_items]
        lines: List[str] = []
        self._append_answer_instructions(lines)
        lines.append("User Question:")
        lines.append(self.presenter.text(query_text, context="user question"))
        lines.append("")

        profile_text = self._truncate_profile(user_profile)
        if profile_text:
            lines.append("User Profile:")
            lines.append(self.presenter.text(profile_text, context="user profile"))
            lines.append("")

        lines.append("Sub-queries:")
        for idx, sub_query in enumerate(sub_queries or [], 1):
            routes = ", ".join(str(route) for route in sub_query.get("routes") or [] if route) or "-"
            query = self.presenter.text(sub_query.get("query", ""), context="sub-query")
            lines.append(f"{idx}. Query: {query}")
            lines.append(f"   Routes: {routes}")
            time_constraint = self.presenter.json_text(sub_query.get("time") or {}, context="time constraint")
            if time_constraint != "-":
                lines.append(f"   Time: {time_constraint}")

        relation_items = [item for item in selected if self._is_relation_item(item)]
        fact_items = [
            item
            for item in selected
            if (item.source == "fact" or "fact" in item.sources) and not self._is_relation_item(item)
        ]
        chunk_items = [
            item
            for item in selected
            if (item.source == "vector" or "vector" in item.sources) and not self._is_relation_item(item)
        ]

        self._append_relation_section(lines, relation_items)
        self._append_fact_section(lines, fact_items)
        self._append_chunk_section(lines, chunk_items)
        return "\n".join(lines).strip()

    @staticmethod
    def _append_answer_instructions(lines: List[str]) -> None:
        lines.append("Answer Instructions:")
        lines.append(
            "- Answer primarily in English. You may preserve non-English names, titles, quoted phrases, "
            "or terms exactly as they appear in the provided evidence."
        )
        lines.append("- Do not introduce new non-English text that is not present in the evidence.")
        lines.append("- Use only the provided retrieval evidence.")
        lines.append("- If evidence is insufficient, say that the evidence is insufficient.")
        lines.append("- Do not invent facts.")
        lines.append("- Do not include stable IDs in the final prose answer.")
        lines.append("")

    @staticmethod
    def _truncate_profile(user_profile: str, limit: int = 2000) -> str:
        text = str(user_profile or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "\n[truncated]"

    @staticmethod
    def _is_relation_item(item: EvidenceItem) -> bool:
        return (
            item.source == "relation"
            or "relation" in item.sources
            or bool(item.metadata.get("relation_uuid"))
            or bool(item.metadata.get("relation_uuids"))
            or item.evidence_type in {"semantic_fact_edge", "semantic_fact_path"}
        )

    @staticmethod
    def _time_text(item: EvidenceItem) -> str:
        return str(json_safe(item.valid_time) or "unknown")

    def _append_fact_section(self, lines: List[str], items: List[EvidenceItem]) -> None:
        if not items:
            return
        lines.append("")
        lines.append("Fact Evidence:")
        for idx, item in enumerate(items, 1):
            lines.append(f"{idx}. Content: {self.presenter.text(item.content, context='fact evidence content')}")
            self._append_trace_fields(lines, item, evidence_source_type="fact")
            lines.append(f"   Time: {self._time_text(item)}")
            lines.append(f"   Source: {item.evidence_type}")
            lines.append(f"   Score: final_score={item.final_score:.3f}, local_score={item.local_score:.3f}")

    def _append_relation_section(self, lines: List[str], items: List[EvidenceItem]) -> None:
        if not items:
            return
        lines.append("")
        lines.append("Relationship Evidence:")
        for idx, item in enumerate(items, 1):
            metadata = item.metadata or {}
            if item.evidence_type == "semantic_fact_edge":
                start = self.presenter.text(metadata.get("start_entity") or "Entity", context="relation start entity")
                target = self.presenter.text(metadata.get("target_entity") or "Entity", context="relation target entity")
                relation = self.presenter.text(metadata.get("relation") or "related_to", context="relation label")
                fact = self.presenter.text(metadata.get("relation_fact") or item.content, context="relation fact")
                lines.append(f"{idx}. {start} --{relation}--> {target}")
                lines.append(f"   Fact: {fact}")
            elif item.evidence_type == "semantic_fact_path":
                labels = self._path_labels(item)
                expression = " ".join(labels) if labels else self.presenter.text(item.content, context="relation path")
                lines.append(f"{idx}. {expression}")
                lines.append(f"   Fact: {self.presenter.text(item.content, context='relation fact')}")
            else:
                labels = self._path_labels(item)
                expression = " -> ".join(labels) if labels else self.presenter.text(item.content, context="relation path")
                lines.append(f"{idx}. {expression}")
                lines.append(f"   Fact: {self.presenter.text(item.content, context='relation fact')}")

            self._append_trace_fields(lines, item, evidence_source_type="relation")
            lines.append(f"   Time: {self._time_text(item)}")
            lines.append(f"   Source: {item.evidence_type}")
            lines.append(
                f"   Recall Sources: {', '.join(str(value) for value in metadata.get('edge_retrieval_sources') or [] if value) or 'unknown'}"
            )
            lines.append(f"   Score: final_score={item.final_score:.3f}, local_score={item.local_score:.3f}")

    def _append_chunk_section(self, lines: List[str], items: List[EvidenceItem]) -> None:
        if not items:
            return
        lines.append("")
        lines.append("Raw Segment Evidence:")
        for idx, item in enumerate(items, 1):
            lines.append(f"{idx}. Content: {self.presenter.text(item.content, context='raw segment evidence content')}")
            self._append_trace_fields(lines, item, evidence_source_type="vector")
            lines.append(f"   Time: {self._time_text(item)}")
            lines.append(f"   Source: {item.evidence_type}")
            lines.append(f"   Score: final_score={item.final_score:.3f}, local_score={item.local_score:.3f}")

    def _append_trace_fields(self, lines: List[str], item: EvidenceItem, evidence_source_type: str) -> None:
        metadata = item.metadata or {}
        fields = [
            ("evidence_type", item.evidence_type),
            ("ori_fact_uuid", item.ori_fact_uuid),
            ("fact_uuid", item.fact_uuid),
            ("chunk_uuid", item.chunk_uuid),
            ("relation_uuid", metadata.get("relation_uuid")),
            ("relation_uuids", self._join_values(metadata.get("relation_uuids"))),
        ]
        lines.append(f"   Evidence Source Type: {evidence_source_type}")
        lines.append(f"   Evidence Type: {item.evidence_type}")
        stable_ids = [f"{name}={value}" for name, value in fields if value]
        if stable_ids:
            lines.append(f"   Stable IDs: {'; '.join(stable_ids)}")

    @staticmethod
    def _join_values(value: object) -> str:
        if not value:
            return ""
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(item) for item in value if item)
        return str(value)

    def _path_labels(self, item: EvidenceItem) -> List[str]:
        labels = []
        for node in item.path or []:
            label = node.get("label", "")
            if label == "RELATES_TO":
                labels.append(f"--{self.presenter.text(node.get('relation') or 'related_to', context='relation label')}-->")
            else:
                labels.append(self.presenter.text(node.get("name") or node.get("uuid") or label, context="path node"))
        return labels
