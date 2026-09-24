"""Compare persisted business data in rehearsal and an isolated restored snapshot."""
import json

from local_server import compose, folder, write


def inspect(stage):
    sql = " UNION ALL ".join(f"SELECT '{name}', COUNT(*) FROM {name}" for name in
                            ["articles", "posts", "feedback_logs", "task_runs", "task_steps", "user_profile_snapshot", "mcp_call_logs", "schema_migrations"])
    shell = 'export MYSQL_PWD="$(cat "$MYSQL_ROOT_PASSWORD_FILE")"\nmysql -uroot -N -B knowledge_post_agent -e "' + sql + '"\n'
    rows = compose(stage, "exec", "-T", "mysql", "sh", "-s", data=shell.encode()).decode().splitlines()
    result = {"mysql": dict(line.split("\t") for line in rows)}
    graph = 'cypher-shell -u neo4j -p "${NEO4J_AUTH#*/}" --format plain "MATCH (n) RETURN count(n) AS nodes; MATCH ()-[r]->() RETURN count(r) AS edges;"\n'
    result["neo4j"] = compose(stage, "exec", "-T", "neo4j", "sh", "-s", data=graph.encode()).decode().strip()
    vector = """import json
from pymilvus import MilvusClient
c=MilvusClient(uri='http://milvus-standalone:19530')
result={}
for name in sorted(c.list_collections()):
    c.flush(name,timeout=60)
    result[name]=c.get_collection_stats(name,timeout=60)
print(json.dumps(result,sort_keys=True))
c.close()
"""
    result["milvus"] = json.loads(compose(stage, "run", "--rm", "--no-deps", "-T", "milvus-mcp", "python", "-c", vector))
    return result


if __name__ == "__main__":
    before, after = inspect("rehearsal"), inspect("restore")
    if before != after:
        raise RuntimeError(f"restored data mismatch: {before} != {after}")
    report = {"match": True, "counts": before}
    write(folder("restore") / "data-verification.json", json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
