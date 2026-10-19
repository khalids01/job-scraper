FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install -r requirements.lock
ENV FASTEMBED_CACHE_PATH=/models TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1
RUN mkdir /models && python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/models')" && chmod -R a+rX /models
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-deps .

# Real MongoDB and Redis in the test image; neither is bundled in runtime.
FROM base AS test
COPY --from=mongo:7.0 /usr/bin/mongod /usr/local/bin/mongod
RUN apt-get update && apt-get install -y --no-install-recommends redis-server libcurl4t64 libssl3t64 liblzma5 libsasl2-2 libsnappy1v5 libzstd1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-dev.lock ./
RUN pip install --no-cache-dir -r requirements-dev.lock
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-deps .
COPY tests ./tests
COPY scripts ./scripts
COPY .env.example compose.yaml ./
RUN ruff check src tests scripts && pytest -q

FROM base AS runtime
RUN groupadd --gid 10001 scraper && useradd --uid 10001 --gid scraper --no-create-home scraper
USER scraper
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]
CMD ["uvicorn", "job_scraper.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
