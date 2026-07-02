#!/usr/bin/env bash
# ============================================================================
# bootstrap.sh : exécuté UNE FOIS au démarrage de la stack par le service
# `bootstrap` dans docker-compose.yml.
#
# Rôle : remplir le warehouse + entraîner le modèle + générer les prédictions
# AVANT que Streamlit ne démarre. Streamlit dépend de la complétion 0 de ce
# service (depends_on.service_completed_successfully), donc l'utilisateur qui
# ouvre la dashboard voit TOUJOURS des données live, jamais un mode démo.
#
# Idempotent : seed UUID5 + ON CONFLICT côté ingestion, dbt rebuilds les
# marts, prédictions upsertées, MLflow Production archive l'ancienne version.
#
# Testable hors Docker (depuis la racine du repo) :
#   PREFECT_API_URL=http://localhost:4200/api \
#   MLFLOW_TRACKING_URI=http://localhost:5001 \
#   POSTGRES_HOST=localhost POSTGRES_PORT=5532 \
#   bash scripts/bootstrap.sh
# ============================================================================
set -euo pipefail

# Le repo entier est monté sur /app par docker-compose ; en local, on part de
# la racine du repo.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

bar() { printf "\n\033[1;36m▶ %s\033[0m\n" "$1"; }

# ----------------------------------------------------------------------------
# 1. dbt deps : installe les packages dbt (dbt_utils).
#    `|| true` : on tolère un échec réseau, les packages sont cachés en volume.
# ----------------------------------------------------------------------------
bar "1/2  dbt deps (packages externes)"
( cd dbt && dbt deps ) || echo "  (dbt deps : ignoré, packages probablement déjà installés)"

# ----------------------------------------------------------------------------
# 2. Pipeline complet via le flow Prefect `cairn-daily-refresh`.
#    On invoque le flow Python directement : la run est enregistrée dans le
#    serveur Prefect (PREFECT_API_URL), lue par la page "État du pipeline" du
#    dashboard affiche une vraie exécution dès le premier lancement.
#
#    Le flow orchestre : seed, ingest, dbt run+test (non bloquant),
#    Great Expectations (non bloquant), ml.train (+register Production),
#    ml.predict, Evidently drift report.
# ----------------------------------------------------------------------------
bar "2/2  Pipeline complet (flow Prefect cairn-daily-refresh)"
python -c "from flows.flows import daily_refresh; daily_refresh()"

cat <<'EOF'

╔══════════════════════════════════════════════════════════════════╗
║   ✓ BOOTSTRAP terminé                                            ║
║   - raw.* + marts.* peuplés                                      ║
║   - xgboost_churn_model promu en Production (MLflow Registry)    ║
║   - analytics.churn_predictions remplie                          ║
║   - Streamlit peut démarrer en mode LIVE                         ║
╚══════════════════════════════════════════════════════════════════╝
EOF
