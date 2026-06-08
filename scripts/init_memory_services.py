from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-servers" / "milvus-mcp"))
sys.path.insert(0, str(ROOT / "mcp-servers" / "neo4j-mcp"))
sys.path.insert(0, str(ROOT / "mcp-servers" / "common"))

from milvus_store import MilvusVectorStore  # noqa: E402
from neo4j_store import Neo4jInterestGraphStore  # noqa: E402
from provider import read_secret  # noqa: E402


def initialize_milvus() -> dict[str, object]:
    store = MilvusVectorStore(
        uri=os.getenv("MILVUS_URI", "http://127.0.0.1:19530"),
        token=read_secret("MILVUS_TOKEN", os.getenv("MILVUS_TOKEN_FILE", "")),
        collection_name=os.getenv("MILVUS_COLLECTION", "user_memory_vectors"),
        dimension=int(os.getenv("MILVUS_DIMENSION", os.getenv("EMBEDDING_DIMENSION", "3072"))),
        timeout_seconds=float(os.getenv("MILVUS_TIMEOUT_SECONDS", "10")),
    )
    try:
        store.initialize()
        return store.health()
    finally:
        store.close()


def initialize_neo4j() -> dict[str, object]:
    store = Neo4jInterestGraphStore(
        uri=os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=read_secret("NEO4J_PASSWORD", os.getenv("NEO4J_PASSWORD_FILE", "")),
        database=os.getenv("NEO4J_DATABASE", "neo4j"),
    )
    try:
        store.initialize()
        return store.health()
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely initialize Milvus and Neo4j memory services.")
    parser.add_argument("--milvus", action="store_true", help="Initialize and validate Milvus.")
    parser.add_argument("--neo4j", action="store_true", help="Initialize Neo4j constraints and indexes.")
    args = parser.parse_args()
    initialize_all = not args.milvus and not args.neo4j
    results: dict[str, object] = {}
    if initialize_all or args.milvus:
        results["milvus"] = initialize_milvus()
    if initialize_all or args.neo4j:
        results["neo4j"] = initialize_neo4j()
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
