.PHONY: help up down logs refresh rebuild \
        seed ingest dbt-build dbt-run dbt-test \
        ge evidently ml-train ml-predict \
        test test-unit test-integration lint \
        observability obs-down clean

SHELL := /bin/bash

COMPOSE      := docker compose
COMPOSE_RUN  := $(COMPOSE) run --rm

# ============================================================================
# Aide
# ============================================================================

help:
	@echo "Cairn Analytics"
	@echo ""
	@echo "Cycle de vie :"
	@echo "  make up          Démarre la stack + bootstrap (Streamlit live en sortie)"
	@echo "  make down        Arrête tous les services"
	@echo "  make logs        Tail des logs"
	@echo "  make refresh     Rejoue le bootstrap + restart Streamlit"
	@echo "  make rebuild     Drop volumes + relance propre"
	@echo ""
	@echo "Observabilité (profil obs) :"
	@echo "  make observability   Prometheus :9090, Grafana :3200, Loki :3100"
	@echo "  make obs-down        Stop la stack obs"
	@echo ""
	@echo "Étapes du pipeline (debug, normalement gérées par bootstrap) :"
	@echo "  make seed ingest dbt-build dbt-run dbt-test"
	@echo "  make ge evidently ml-train ml-predict"
	@echo ""
	@echo "Tests + qualité :"
	@echo "  make test-unit test-integration test lint"
	@echo ""
	@echo "  make clean       Nettoie les fichiers intermédiaires"


# ============================================================================
# Cycle de vie
# ============================================================================

up:
	$(COMPOSE) up -d
	@echo ""
	@echo "Streamlit  http://localhost:8601"
	@echo "API        http://localhost:8100/docs"
	@echo "MLflow     http://localhost:5001"
	@echo "Prefect    http://localhost:4200"
	@echo ""
	@echo "Le service 'bootstrap' remplit la base + entraîne le modèle."
	@echo "Streamlit attend sa complétion (1 à 3 min au premier lancement)."
	@echo "Suivi : docker compose logs -f bootstrap"

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

refresh:
	$(COMPOSE) up -d --force-recreate --no-deps bootstrap
	$(COMPOSE) restart streamlit
	@echo "Bootstrap relancé + cache Streamlit purgé."

rebuild:
	$(COMPOSE) down -v
	$(MAKE) up


# ============================================================================
# Étapes du pipeline (utiles en debug pour itérer sur une étape isolée)
# ============================================================================

seed:
	mkdir -p data/raw
	$(COMPOSE_RUN) pipeline python -m seed.main --output-dir data/raw

ingest:
	$(COMPOSE_RUN) pipeline python -m ingestion.main --raw-dir data/raw

dbt-build:
	$(COMPOSE_RUN) dbt dbt deps
	$(COMPOSE_RUN) dbt dbt run
	$(COMPOSE_RUN) dbt dbt test

dbt-run:  ; $(COMPOSE_RUN) dbt dbt run
dbt-test: ; $(COMPOSE_RUN) dbt dbt test

ge:
	$(COMPOSE_RUN) pipeline python -m great_expectations.runner

evidently:
	$(COMPOSE_RUN) pipeline python -m monitoring.evidently_jobs

ml-train:
	@mkdir -p ml/models
	$(COMPOSE_RUN) pipeline python -m ml.train --model both

ml-predict:
	$(COMPOSE_RUN) pipeline python -m ml.predict


# ============================================================================
# Tests + qualité
# ============================================================================

# Tourne sur l'HÔTE (pas dans Docker), comme test-integration et comme la CI :
# les tests unitaires couvrent l'API (fastapi) et les flows (prefect), absents
# de l'image pipeline. La CI fait exactement `pip install -r requirements-dev.txt`
# puis `pytest tests/unit`. En local, même prérequis (idéalement dans un venv) :
#   python -m venv .venv && source .venv/bin/activate
#   pip install -r requirements-dev.txt
test-unit:
	pytest tests/unit -ra -q

# Tourne sur l'HÔTE : testcontainers pilote le démon Docker pour démarrer son
# propre Postgres. Même prérequis : pip install -r requirements-dev.txt
test-integration:
	pytest tests/integration -ra -q -m "not slow"

test: test-unit test-integration

# Sur l'HÔTE également (ruff est dans requirements-dev, pas dans l'image pipeline).
# `ruff check .` couvre TOUT le projet (dashboard inclus), selon la config pyproject.
lint:
	ruff check .


# ============================================================================
# Observabilité
# ============================================================================

observability:
	$(COMPOSE) --profile obs up -d prometheus loki promtail grafana
	@echo "Prometheus :9090, Grafana :3200 (admin/admin), Loki :3100"

obs-down:
	$(COMPOSE) --profile obs down


# ============================================================================
# Nettoyage
# ============================================================================

clean:
	rm -rf dbt/target dbt/dbt_packages
	rm -rf data/raw/* data/ge_reports/* data/evidently_reports/*
	rm -rf ml/models/*
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
