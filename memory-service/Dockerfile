FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY memory-service/memory_service.py /app/memory-service/memory_service.py
COPY memory-service/mempro_backend.py /app/memory-service/mempro_backend.py
COPY memory-service/vendor /app/memory-service/vendor

RUN pip install --no-cache-dir -r /app/memory-service/vendor/mem_pro/requirements.txt

RUN groupadd --system --gid 10001 knowmate \
    && useradd --system --uid 10001 --gid knowmate --home-dir /app --shell /usr/sbin/nologin knowmate \
    && mkdir -p /app/memory-service/data \
    && chown -R knowmate:knowmate /app

WORKDIR /app
EXPOSE 8091
USER knowmate
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; r=urllib.request.Request('http://127.0.0.1:8091/health',headers={'Authorization':'Bearer '+os.environ.get('MEMORY_SERVICE_TOKEN','')}); urllib.request.urlopen(r,timeout=2).read()"
CMD ["python", "memory-service/memory_service.py"]
