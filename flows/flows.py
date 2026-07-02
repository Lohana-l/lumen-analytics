"""Flows Prefect : DAG déclaratif pour le pipeline Cairn.

Pourquoi Prefect et pas un cron classique ?
    • Observabilité native (UI + alerting + SLA)
    • Retries + notifications d'échec en configuration, pas en boilerplate
    • Les deployments épinglent le travail sur un worker pool (``cairn-pool``), local ≡ prod

Flows
-----
daily_refresh     : seed, ingest, dbt build, GE suite, train, predict, Evidently
intraday_predict  : predict + evidently (toutes les 2h), utilise le modèle entraîné

Les schedules sont définis dans deployments.py pour garder ce module pur.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from prefect import flow, get_run_logger, task
from prefect.tasks import exponential_backoff

ROOT = Path(__file__).resolve().parents[1]


# ----------------------------------------------------------------------
# Tasks : wrappers fins autour des CLIs pour que Prefect gère retries/logs
# ----------------------------------------------------------------------
@task(retries=2, retry_delay_seconds=exponential_backoff(10))
def seed_task(accounts: int = 2_000) -> None:
    log = get_run_logger()
    log.info("seeding %d accounts", accounts)
    subprocess.run(
        ["python", "-m", "seed.main", "--output-dir", "data/raw",
         "--accounts", str(accounts)],
        check=True, cwd=ROOT,
    )


@task(retries=3, retry_delay_seconds=exponential_backoff(5))
def ingest_task() -> None:
    log = get_run_logger()
    log.info("loading CSVs into Postgres")
    subprocess.run(
        ["python", "-m", "ingestion.main", "--raw-dir", "data/raw"],
        check=True, cwd=ROOT,
    )


@task(retries=1)
def dbt_build_task() -> None:
    log = get_run_logger()
    log.info("dbt run (build) + dbt test (qualité, non bloquant)")
    # Le build des modèles DOIT réussir (sinon pas de marts pour le dashboard).
    subprocess.run(["dbt", "run"], check=True, cwd=ROOT / "dbt")
    # dbt test = contrôle qualité d'observabilité : on le lance, on logge le
    # résultat, mais on ne fait PAS échouer le refresh dessus. Les résultats
    # restent visibles sur la page Monitoring.
    res = subprocess.run(["dbt", "test"], cwd=ROOT / "dbt")
    if res.returncode != 0:
        log.warning("dbt test : des tests qualité ont échoué (non bloquant, voir Monitoring).")


@task(retries=1)
def ge_checks_task() -> None:
    log = get_run_logger()
    log.info("Great Expectations suites (qualité, non bloquant)")
    # Idem : les attentes GE sont de l'observabilité qualité, pas un motif de
    # crash du pipeline. On exécute, on logge, le refresh continue.
    res = subprocess.run(
        ["python", "-m", "great_expectations.runner"],
        cwd=ROOT,
    )
    if res.returncode != 0:
        log.warning("Great Expectations : des attentes ont échoué (non bloquant, voir Monitoring).")


@task(retries=1)
def train_task() -> None:
    log = get_run_logger()
    log.info("training churn model (logreg + xgb)")
    subprocess.run(["python", "-m", "ml.train", "--model", "both"],
                   check=True, cwd=ROOT)


@task(retries=2)
def predict_task() -> None:
    log = get_run_logger()
    log.info("batch predictions vers analytics.churn_predictions")
    subprocess.run(["python", "-m", "ml.predict"], check=True, cwd=ROOT)


@task(retries=1)
def evidently_task() -> None:
    log = get_run_logger()
    log.info("Evidently drift report (qualité, non bloquant)")
    # Même politique que dbt test et GE : le rapport de dérive est de
    # l'observabilité, pas une étape de production de données. Un échec est
    # loggé et visible sur la page Monitoring, mais ne doit pas faire planter
    # tout le daily_refresh.
    res = subprocess.run(["python", "-m", "monitoring.evidently_jobs"],
                         cwd=ROOT)
    if res.returncode != 0:
        log.warning("Evidently : génération du rapport échouée (non bloquant, voir Monitoring).")


# ----------------------------------------------------------------------
# Flows
# ----------------------------------------------------------------------
@flow(name="cairn-daily-refresh", log_prints=True)
def daily_refresh(accounts: int = 2_000) -> None:
    """Rebuild complet nocturne : source de vérité pour Streamlit + API."""
    seed_task(accounts)
    ingest_task()
    dbt_build_task()
    ge_checks_task()
    train_task()
    predict_task()
    evidently_task()


@flow(name="cairn-intraday-predict", log_prints=True)
def intraday_predict() -> None:
    """Boucle rapide : re-scoring + vérification drift sans ré-entraînement."""
    predict_task()
    evidently_task()


if __name__ == "__main__":
    daily_refresh()
