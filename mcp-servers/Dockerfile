FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_SERVER=embedding-mcp

WORKDIR /app
COPY mcp-servers/requirements.txt /app/mcp-servers/requirements.txt
RUN pip install --no-cache-dir -r /app/mcp-servers/requirements.txt
COPY mcp-servers/ /app/mcp-servers/
RUN groupadd --system --gid 10001 knowmate \
    && useradd --system --uid 10001 --gid knowmate --home-dir /app --shell /usr/sbin/nologin knowmate \
    && chown -R knowmate:knowmate /app

EXPOSE 7001 7002 7003 7004
USER knowmate
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; ports={'embedding-mcp':'7001','fetch-mcp':'7002','milvus-mcp':'7003','neo4j-mcp':'7004'}; port=os.getenv('PORT') or ports.get(os.getenv('MCP_SERVER','embedding-mcp'),'7001'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=3).read()"
CMD ["sh", "-c", "python /app/mcp-servers/$MCP_SERVER/server.py"]
