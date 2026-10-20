FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AUTOBL_DATA_DIR=/data \
    AUTOBL_RUN_MIGRATIONS=1

WORKDIR /app

# curl is used by the container health check.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first so the layer is cached between builds.
COPY apps/api/requirements.txt /app/requirements.txt
# psycopg is the PostgreSQL driver - it is not part of the desktop bundle.
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && pip install --no-cache-dir "psycopg[binary]>=3.1,<4"

COPY apps/api /app
COPY infrastructure/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /data

RUN useradd --create-home --uid 10001 autobl && chown -R autobl:autobl /app /data
USER autobl

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
