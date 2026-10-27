FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/noctis-loot.db \
    API_HOST=0.0.0.0 \
    API_PORT=8080

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot

# Run as a plain user; the database lives on the /data volume.
RUN useradd --system --uid 1000 --home /app loot && mkdir -p /data && chown loot /data
USER loot
VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)"

CMD ["python", "-m", "bot"]
