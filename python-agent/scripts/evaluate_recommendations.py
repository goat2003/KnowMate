from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.recommendation import RecommendationRanker, RecommendationSettings
from app.recommendation.evaluation import evaluate_ranked_items


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate offline recommendation ranking fixtures.")
    parser.add_argument("--input", required=True, help="Path to a JSON or JSONL offline recommendation fixture.")
    parser.add_argument("--output", default="", help="Optional path to write the metrics report.")
    parser.add_argument("--k", type=int, default=5, help="Cutoff for @K metrics.")
    args = parser.parse_args()

    payload = _read_payload(Path(args.input))
    articles = list(payload.get("articles", []))
    ranker = RecommendationRanker(RecommendationSettings())
    ranked = ranker.rank(
        articles,
        dict(payload.get("user_profile_snapshot", {})),
        mcp_signals={
            str(item.get("article_id", "")): {
                "milvus_matches": item.get("milvus_matches"),
                "neo4j_topics": item.get("neo4j_topics"),
            }
            for item in articles
        },
    )
    by_id = {str(item.get("article_id", "")): item for item in articles}
    metric_items = []
    for item in ranked:
        original = by_id.get(item.article_id, {})
        metric_items.append(
            {
                "article_id": item.article_id,
                "label": int(original.get("label", 0)),
                "relevance": float(original.get("relevance", original.get("label", 0))),
                "topic": item.primary_topic,
                "url": original.get("url", ""),
                "title": original.get("title", ""),
            }
        )

    report = evaluate_ranked_items(metric_items, k=args.k)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    return 0


def _read_payload(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".jsonl":
        return {"articles": [json.loads(line) for line in text.splitlines() if line.strip()]}
    return json.loads(text)


if __name__ == "__main__":
    sys.exit(main())
