# LedgerLens — production container image (see DEPLOYMENT.md).
# Build from the project root:  docker build -f deploy/Dockerfile .

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY deploy/requirements-prod.txt ./requirements-prod.txt
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY fin_db.py fin.py market_api.py analyst_llm.py agent.py main.py ./
COPY static/ static/

# Run as a non-root user; /app holds no persistent state (Postgres owns the data).
RUN useradd --system --uid 10001 --no-create-home ledgerlens \
    && chown -R ledgerlens:ledgerlens /app
USER ledgerlens

EXPOSE 8083

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8083/health', timeout=4).status==200 else 1)"

# Behind a reverse proxy: trust X-Forwarded-* headers from any local proxy hop.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8083", \
     "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]
