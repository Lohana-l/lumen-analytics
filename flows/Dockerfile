FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev libgomp1 git curl \
 && rm -rf /var/lib/apt/lists/*

COPY flows/requirements.txt ./requirements.txt
RUN pip install --upgrade pip \
 && pip install -r requirements.txt

# dbt is installed so Prefect can shell out to it.
RUN pip install dbt-core==1.9.1 dbt-postgres==1.9.0

COPY . ./

RUN chmod +x flows/entrypoint.sh

CMD ["bash", "flows/entrypoint.sh"]
