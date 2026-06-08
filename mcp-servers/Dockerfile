FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_SERVER=embedding-mcp

WORKDIR /app
COPY mcp-servers/requirements.txt /app/mcp-servers/requirements.txt
RUN pip install --no-cache-dir -r /app/mcp-servers/requirements.txt
COPY mcp-servers/ /app/mcp-servers/

CMD ["sh", "-c", "python /app/mcp-servers/$MCP_SERVER/server.py"]
