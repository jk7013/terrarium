FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock.txt /app/requirements.lock.txt
RUN pip install --no-cache-dir -r /app/requirements.lock.txt

FROM base AS test

COPY requirements-dev.txt /app/requirements-dev.txt
RUN pip install --no-cache-dir -r /app/requirements-dev.txt

COPY app /app/app
COPY benchmarks /app/benchmarks
COPY tests /app/tests
COPY scripts /app/scripts
COPY pytest.ini /app/pytest.ini

CMD ["python", "-m", "pytest", "-q"]

FROM base AS runtime

COPY app /app/app
COPY static /app/static
COPY pg_ingest_law_article.py /app/pg_ingest_law_article.py
COPY build_law_dev_small.py /app/build_law_dev_small.py
COPY run_retrieval_debug.py /app/run_retrieval_debug.py

EXPOSE 9000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
