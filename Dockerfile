FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install -r requirements.lock
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-deps .

FROM base AS test
COPY requirements-dev.lock ./
RUN pip install -r requirements-dev.lock
COPY tests ./tests
RUN ruff check src tests && pytest -q

FROM base AS runtime
RUN groupadd --gid 10001 scraper && useradd --uid 10001 --gid scraper --no-create-home scraper \
    && mkdir /data && chown scraper:scraper /data
ENV DATABASE_PATH=/data/jobs.sqlite3
USER scraper
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]
CMD ["uvicorn", "job_scraper.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
