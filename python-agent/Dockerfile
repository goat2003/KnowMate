FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY shared/python-security-constraints.txt /app/shared/python-security-constraints.txt
COPY python-agent/requirements.txt /app/python-agent/requirements.txt
RUN pip install --no-cache-dir --upgrade "pip>=26.2" "setuptools>=83" \
    && pip install --no-cache-dir -r /app/python-agent/requirements.txt

COPY python-agent/ .
RUN groupadd --system --gid 10001 knowmate \
    && useradd --system --uid 10001 --gid knowmate --home-dir /app --shell /usr/sbin/nologin knowmate \
    && chown -R knowmate:knowmate /app

EXPOSE 50051 9101
USER knowmate
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python healthcheck.py
CMD ["python", "server.py"]
