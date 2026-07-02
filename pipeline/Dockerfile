# Pipeline image - runs seed (synthetic data) + ingestion (CSV vers Postgres).
# Kept as a single image: both share the same Python deps and running them
# as sibling services would bloat docker-compose unnecessarily.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY pipeline/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY seed      ./seed
COPY ingestion ./ingestion

# No default CMD - docker-compose specifies the entrypoint per invocation.
