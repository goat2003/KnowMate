"""Business checks for rehearsal. Writes one visibly tagged test feedback."""
import json
from datetime import datetime, timezone

from local_server import compose, folder, request, write


def api(path, body=None):
    code, raw = request("rehearsal", "/api" + path, body=body, method="POST" if body is not None else "GET")
    data = json.loads(raw)
    if code != 200 or data.get("ok") is False:
        raise RuntimeError(f"business check failed: {path}, HTTP {code}")
    return data


def main():
    evidence = {"time": datetime.now(timezone.utc).isoformat()}
    articles = api("/articles")["items"]
    if not articles or any("example.com/mock" in a.get("url", "") for a in articles):
        raise RuntimeError("expected real source articles")
    evidence["real_articles"] = len(articles)
    posts = api("/posts")["items"]
    if not posts:
        raise RuntimeError("expected generated rehearsal posts")
    evidence["posts"] = len(posts)
    duplicate = api("/runs/articles", {})["result"]
    if duplicate["status"] != "completed" or duplicate["new_articles"] != 0:
        raise RuntimeError("duplicate run did not safely skip existing articles")
    evidence["dedupe_run"] = duplicate
    post = posts[0]
    post_id = post.get("post_uid") or post.get("post_id") or post.get("id")
    result = api("/feedback", {"post_id": post_id, "user_id": "local-acceptance",
                 "rating": 5, "feedback_text": "[LOCAL ACCEPTANCE] Prefer engineering examples; rehearsal only."})["result"]
    if result["status"] != "completed":
        raise RuntimeError("feedback did not complete")
    logs = api("/mcp-call-logs?run_id=" + result["run_id"])["items"]
    logs = [log for log in logs if log["run_id"] == result["run_id"]]
    if len(logs) < 3 or any(log["status"] != "success" for log in logs):
        raise RuntimeError("feedback completed with unsuccessful memory side effects")
    evidence["feedback"] = result
    profile = api("/profile?user_id=local-acceptance")["profile"]
    evidence["profile_version"] = profile["version"]
    for service in ["embedding-mcp", "milvus-mcp", "neo4j-mcp", "fetch-mcp"]:
        port = {"embedding-mcp": 7001, "fetch-mcp": 7002, "milvus-mcp": 7003, "neo4j-mcp": 7004}[service]
        code = f"import urllib.request; print(urllib.request.urlopen('http://{service}:{port}/health').read().decode())"
        evidence[service] = json.loads(compose("rehearsal", "exec", "-T", "python-agent", "python", "-c", code))
    auth_probe = """import urllib.request, urllib.error
try:
    urllib.request.urlopen('http://goframe-backend:8080/runs')
except urllib.error.HTTPError as e:
    assert e.code == 401
else:
    raise RuntimeError('backend missing authentication')
import grpc, agent_pb2, agent_pb2_grpc
try:
    agent_pb2_grpc.AgentServiceStub(grpc.insecure_channel('python-agent:50051')).HealthCheck(agent_pb2.HealthCheckRequest(),timeout=5)
except grpc.RpcError as e:
    assert e.code() == grpc.StatusCode.UNAUTHENTICATED
else:
    raise RuntimeError('agent missing authentication')
print('HTTP and gRPC unauthenticated requests rejected')
"""
    evidence["internal_authentication"] = compose("rehearsal", "exec", "-T", "python-agent", "python", "-c", auth_probe).decode().strip()
    write(folder("rehearsal") / "business-report.json", json.dumps(evidence, ensure_ascii=False, indent=2))
    print(json.dumps({"real_articles": len(articles), "posts": len(posts), "feedback_run": result["run_id"],
                      "profile_version": profile["version"], "internal_authentication": "passed"}, indent=2))


if __name__ == "__main__":
    main()
