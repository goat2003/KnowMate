"""Authenticated container health check. Never prints credentials."""
import grpc

import agent_pb2
import agent_pb2_grpc
from app.config import read_secret


def main() -> None:
    token = read_secret("AGENT_GRPC_AUTH_TOKEN")
    metadata = [("authorization", f"Bearer {token}")] if token else []
    with grpc.insecure_channel("127.0.0.1:50051") as channel:
        result = agent_pb2_grpc.AgentServiceStub(channel).HealthCheck(
            agent_pb2.HealthCheckRequest(client="docker"), metadata=metadata, timeout=3
        )
    if result.status != "SERVING":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
