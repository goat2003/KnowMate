FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY python-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY python-agent/ .
RUN groupadd --system --gid 10001 knowmate \
    && useradd --system --uid 10001 --gid knowmate --home-dir /app --shell /usr/sbin/nologin knowmate \
    && chown -R knowmate:knowmate /app

EXPOSE 50051 9101
USER knowmate
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import grpc, agent_pb2, agent_pb2_grpc; c=grpc.insecure_channel('127.0.0.1:50051'); agent_pb2_grpc.AgentServiceStub(c).HealthCheck(agent_pb2.HealthCheckRequest(client='docker'), timeout=3)"
CMD ["python", "server.py"]
