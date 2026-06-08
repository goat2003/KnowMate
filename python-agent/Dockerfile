FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY python-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY python-agent/ .

EXPOSE 50051
CMD ["python", "server.py"]
