from __future__ import annotations

import hashlib
import json
import re
from typing import Any


JsonDict = dict[str, Any]


class InterestGraphError(RuntimeError):
    pass


def stable_event_id(payload: JsonDict) -> str:
    content = {key: value for key, value in payload.items() if key != "event_id"}
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_interest_event(payload: JsonDict) -> JsonDict:
    user_id = str(payload.get("user_id") or "default-user").strip() or "default-user"
    weights: dict[str, float] = {}
    topics = payload.get("topics", [])
    if isinstance(topics, list):
        for topic in topics:
            if not isinstance(topic, dict):
                continue
            name = str(topic.get("name") or "").strip()
            if name:
                weights[name] = weights.get(name, 0.0) + float(topic.get("weight", topic.get("delta", 0.1)) or 0.1)
    snapshot = payload.get("snapshot", {})
    if isinstance(snapshot, dict):
        interests = snapshot.get("interests", "")
        if isinstance(interests, str):
            values = interests.replace(";", ",").split(",")
        elif isinstance(interests, list):
            values = interests
        else:
            values = []
        for raw in values:
            name = str(raw).strip()
            if name:
                weights[name] = max(weights.get(name, 0.0), 0.7)
    feedback = payload.get("extracted_feedback", [])
    if isinstance(feedback, list):
        text = " ".join(str(item) for item in feedback).lower()
        for candidate in ["AI", "knowledge-management", "engineering", "workflow", "summary"]:
            if candidate.lower() in text:
                weights[candidate] = weights.get(candidate, 0.0) + 0.05
    event = {
        "user_id": user_id,
        "topics": [{"name": name, "weight": max(-1.0, min(weight, 1.0))} for name, weight in sorted(weights.items())],
        "sentiment": str(payload.get("sentiment") or "neutral"),
    }
    event["event_id"] = str(payload.get("event_id") or stable_event_id(event))
    return event


class MemoryInterestGraphStore:
    RELATED = {
        "AI": [("agents", 0.9), ("LLM", 0.86), ("workflow", 0.82)],
        "knowledge-management": [("graph", 0.9), ("memory", 0.86), ("taxonomy", 0.8)],
        "engineering": [("testing", 0.9), ("architecture", 0.86), ("reliability", 0.82)],
    }

    def __init__(self) -> None:
        self.graph: dict[str, dict[str, float]] = {}
        self.events: set[str] = set()

    def initialize(self) -> None:
        return

    def close(self) -> None:
        return

    def health(self) -> JsonDict:
        return {"provider": "memory", "users": len(self.graph), "events": len(self.events)}

    def query_user_interests(self, user_id: str, limit: int = 20) -> list[JsonDict]:
        graph = self.graph.get(user_id, {})
        return [
            {"name": name, "weight": round(weight, 4)}
            for name, weight in sorted(graph.items(), key=lambda item: item[1], reverse=True)[: max(1, min(limit, 100))]
        ]

    def update_user_interests(self, event: JsonDict) -> JsonDict:
        event_id = str(event["event_id"])
        user_id = str(event["user_id"])
        if event_id in self.events:
            return {
                "updated": True,
                "applied": False,
                "event_id": event_id,
                "user_id": user_id,
                "topics": self.query_user_interests(user_id),
                "mock": True,
            }
        self.events.add(event_id)
        graph = self.graph.setdefault(user_id, {})
        for topic in event.get("topics", []):
            name = str(topic["name"])
            graph[name] = max(0.0, min(1.0, graph.get(name, 0.0) + float(topic["weight"])))
        return {
            "updated": True,
            "applied": True,
            "event_id": event_id,
            "user_id": user_id,
            "topics": self.query_user_interests(user_id),
            "mock": True,
        }

    def get_related_topics(self, topic: str, limit: int = 5) -> list[JsonDict]:
        values = self.RELATED.get(topic, [])
        return [{"name": name, "score": score, "path": [topic, name]} for name, score in values[: max(1, min(limit, 20))]]

    def explain_recommendation(self, user_id: str, article: JsonDict) -> JsonDict:
        article_topics = _article_topics(article)
        interests = self.graph.get(user_id, {})
        matched = [
            {"name": topic, "weight": round(interests[topic], 4), "path": [user_id, topic]}
            for topic in article_topics
            if topic in interests
        ]
        related_paths: list[JsonDict] = []
        for interest, weight in interests.items():
            for related, relation_weight in self.RELATED.get(interest, []):
                if related in article_topics:
                    related_paths.append(
                        {
                            "interest": interest,
                            "topic": related,
                            "interest_weight": round(weight, 4),
                            "relation_weight": relation_weight,
                            "path": [user_id, interest, related],
                        }
                    )
        scores = [float(item["weight"]) for item in matched]
        scores.extend(float(item["interest_weight"]) * float(item["relation_weight"]) for item in related_paths)
        score = round(max(scores, default=0.0), 4)
        reasons = [f"matched user topic `{item['name']}` with weight {item['weight']}" for item in matched]
        reasons.extend(
            f"related user topic `{item['interest']}` to article topic `{item['topic']}`"
            for item in related_paths
        )
        if not reasons:
            reasons = ["no graph-derived topic match"]
        return {
            "user_id": user_id,
            "score": score,
            "reasons": reasons,
            "matched_topics": matched,
            "related_paths": related_paths,
            "mock": True,
        }


CONSTRAINTS_AND_INDEXES = [
    "CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.id IS UNIQUE",
    "CREATE CONSTRAINT topic_name_unique IF NOT EXISTS FOR (t:Topic) REQUIRE t.name IS UNIQUE",
    "CREATE CONSTRAINT interest_event_id_unique IF NOT EXISTS FOR (e:InterestEvent) REQUIRE e.id IS UNIQUE",
    "CREATE INDEX interest_event_user_id IF NOT EXISTS FOR (e:InterestEvent) ON (e.user_id)",
]

UPDATE_QUERY = """
MERGE (e:InterestEvent {id: $event_id})
ON CREATE SET e.user_id = $user_id, e.created_at = timestamp(), e.applied = false
WITH e, e.applied AS already_applied
CALL (e, already_applied) {
  WITH e, already_applied
  WHERE already_applied = false
  UNWIND $topics AS topic
  MERGE (u:User {id: $user_id})
  MERGE (t:Topic {name: topic.name})
  MERGE (u)-[r:INTERESTED_IN]->(t)
  SET r.weight = CASE
      WHEN coalesce(r.weight, 0.0) + topic.weight < 0.0 THEN 0.0
      WHEN coalesce(r.weight, 0.0) + topic.weight > 1.0 THEN 1.0
      ELSE coalesce(r.weight, 0.0) + topic.weight
    END,
    r.updated_at = timestamp(),
    r.last_event_id = $event_id
  RETURN count(*) AS updates
}
SET e.applied = true
RETURN NOT already_applied AS applied
""".strip()

QUERY_INTERESTS = """
MATCH (:User {id: $user_id})-[r:INTERESTED_IN]->(t:Topic)
RETURN t.name AS name, r.weight AS weight
ORDER BY weight DESC, name ASC
LIMIT $limit
""".strip()

QUERY_RELATED = """
MATCH (source:Topic {name: $topic})-[r:RELATED_TO]->(target:Topic)
RETURN target.name AS name, r.weight AS score, [source.name, target.name] AS path
ORDER BY score DESC, name ASC
LIMIT $limit
""".strip()

EXPLAIN_QUERY = """
MATCH (:User {id: $user_id})-[interest:INTERESTED_IN]->(source:Topic)
UNWIND $article_topics AS article_topic
OPTIONAL MATCH (source)-[related:RELATED_TO]->(target:Topic {name: article_topic})
WITH source, interest, article_topic, related, target
WHERE source.name = article_topic OR target IS NOT NULL
RETURN source.name AS interest_name,
       interest.weight AS interest_weight,
       article_topic AS article_topic,
       coalesce(related.weight, 1.0) AS relation_weight,
       CASE WHEN target IS NULL
         THEN [source.name]
         ELSE [source.name, target.name]
       END AS path
ORDER BY interest_weight * relation_weight DESC
LIMIT 20
""".strip()


class Neo4jInterestGraphStore:
    def __init__(
        self,
        *,
        driver: object | None = None,
        uri: str = "bolt://127.0.0.1:7687",
        user: str = "neo4j",
        password: str = "",
        database: str = "neo4j",
    ) -> None:
        self.driver = driver
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database

    def initialize(self) -> None:
        if self.driver is None:
            if not self.password:
                raise InterestGraphError("NEO4J_PASSWORD is required when NEO4J_PROVIDER=neo4j")
            try:
                from neo4j import GraphDatabase
            except ImportError as exc:  # pragma: no cover - installed in production image
                raise InterestGraphError("neo4j package is required for real Neo4j mode") from exc
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        self.driver.verify_connectivity()
        for statement in CONSTRAINTS_AND_INDEXES:
            self._execute(statement)

    def close(self) -> None:
        close = getattr(self.driver, "close", None)
        if callable(close):
            close()

    def health(self) -> JsonDict:
        if self.driver is None:
            raise InterestGraphError("Neo4j driver is unavailable")
        self.driver.verify_connectivity()
        return {"provider": "neo4j", "uri": self.uri, "database": self.database, "connected": True}

    def query_user_interests(self, user_id: str, limit: int = 20) -> list[JsonDict]:
        return [
            {"name": str(record.get("name", "")), "weight": round(float(record.get("weight", 0.0)), 4)}
            for record in self._execute(
                QUERY_INTERESTS,
                {"user_id": user_id, "limit": max(1, min(int(limit), 100))},
                read=True,
            )
        ]

    def update_user_interests(self, event: JsonDict) -> JsonDict:
        records = self._execute(
            UPDATE_QUERY,
            {"event_id": event["event_id"], "user_id": event["user_id"], "topics": event.get("topics", [])},
        )
        applied = bool(records[0].get("applied")) if records else False
        return {
            "updated": True,
            "applied": applied,
            "event_id": event["event_id"],
            "user_id": event["user_id"],
            "topics": self.query_user_interests(str(event["user_id"])),
            "mock": False,
        }

    def get_related_topics(self, topic: str, limit: int = 5) -> list[JsonDict]:
        return [
            {
                "name": str(record.get("name", "")),
                "score": round(float(record.get("score", 0.0)), 4),
                "path": list(record.get("path", [])),
            }
            for record in self._execute(
                QUERY_RELATED,
                {"topic": topic, "limit": max(1, min(int(limit), 20))},
                read=True,
            )
        ]

    def explain_recommendation(self, user_id: str, article: JsonDict) -> JsonDict:
        records = self._execute(
            EXPLAIN_QUERY,
            {"user_id": user_id, "article_topics": _article_topics(article)},
            read=True,
        )
        matched: list[JsonDict] = []
        related_paths: list[JsonDict] = []
        scores: list[float] = []
        for record in records:
            interest_name = str(record.get("interest_name", ""))
            article_topic = str(record.get("article_topic", ""))
            interest_weight = float(record.get("interest_weight", 0.0))
            relation_weight = float(record.get("relation_weight", 0.0))
            scores.append(interest_weight * relation_weight)
            if interest_name == article_topic:
                matched.append({"name": interest_name, "weight": interest_weight, "path": record.get("path", [])})
            else:
                related_paths.append(
                    {
                        "interest": interest_name,
                        "topic": article_topic,
                        "interest_weight": interest_weight,
                        "relation_weight": relation_weight,
                        "path": record.get("path", []),
                    }
                )
        reasons = [f"matched user topic `{item['name']}` with weight {item['weight']}" for item in matched]
        reasons.extend(
            f"related user topic `{item['interest']}` to article topic `{item['topic']}`"
            for item in related_paths
        )
        return {
            "user_id": user_id,
            "score": round(max(scores, default=0.0), 4),
            "reasons": reasons or ["no graph-derived topic match"],
            "matched_topics": matched,
            "related_paths": related_paths,
            "mock": False,
        }

    def _execute(self, query: str, parameters: JsonDict | None = None, *, read: bool = False) -> list[JsonDict]:
        if self.driver is None:
            raise InterestGraphError("Neo4j driver is unavailable")
        kwargs: dict[str, object] = {"database_": self.database, "parameters_": parameters or {}}
        if read:
            try:
                from neo4j import RoutingControl

                kwargs["routing_"] = RoutingControl.READ
            except ImportError:
                pass
        result = self.driver.execute_query(query, **kwargs)
        records = getattr(result, "records", result[0] if isinstance(result, tuple) else result)
        return [dict(record) for record in records or []]


def _article_topics(article: JsonDict) -> list[str]:
    explicit = article.get("topics", [])
    if isinstance(explicit, str):
        topics = [part.strip() for part in explicit.replace(";", ",").split(",")]
    elif isinstance(explicit, list):
        topics = [str(part).strip() for part in explicit]
    else:
        topics = []
    if topics:
        return sorted(set(topic for topic in topics if topic))
    text = f"{article.get('title', '')} {article.get('summary', '')}".strip()
    return sorted(set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,63}", text)))
