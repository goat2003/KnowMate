"""Replay the existing tagged rehearsal feedback through authenticated gRPC.

Reuses its run ID and vector ID; creates no additional SQL feedback/profile.
"""
import json

from local_server import compose, folder, write


def main():
    report = json.loads((folder("rehearsal") / "business-report.json").read_text())
    run_id = report["feedback"]["run_id"]
    script = '''import json, grpc, agent_pb2, agent_pb2_grpc
from app.config import read_secret
run_id = RUN_ID
request = agent_pb2.ProcessFeedbackRequest(
    run_id=run_id,
    user_profile_snapshot={"user_id":"local-acceptance","feedback_count":"0"},
    feedback=[agent_pb2.FeedbackItem(user_id="local-acceptance", feedback_text="[LOCAL ACCEPTANCE] Prefer engineering examples; rehearsal only.",rating=5)],
    mcp_policy=agent_pb2.McpPolicy(enable_embedding=True,enable_milvus=True,enable_neo4j=True,mock_transport=False))
with grpc.insecure_channel("python-agent:50051") as channel:
    response=agent_pb2_grpc.AgentServiceStub(channel).ProcessFeedback(request,metadata=[("authorization","Bearer "+read_secret("AGENT_GRPC_AUTH_TOKEN"))],timeout=90)
logs=[{"tool":x.tool_name,"status":x.status} for x in response.mcp_call_logs]
assert len(logs)==3 and all(x["status"]=="success" for x in logs), logs
print(json.dumps({"run_id":run_id,"mcp_logs":logs,"same_feedback_replayed":True}))
'''.replace("RUN_ID", repr(run_id))
    data = json.loads(compose("rehearsal", "exec", "-T", "python-agent", "python", "-c", script))
    write(folder("rehearsal") / "memory-replay-report.json", json.dumps(data, indent=2))
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
