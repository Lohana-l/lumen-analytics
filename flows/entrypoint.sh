#!/bin/bash
# Mêmes garde-fous que scripts/bootstrap.sh : variable non définie ou échec
# dans un pipe = arrêt immédiat, pas de demi-démarrage silencieux.
set -euo pipefail

# Démarre le serveur Prefect en arrière-plan
prefect server start --host 0.0.0.0 --port 4200 &

# Attend que l'API soit prête
echo "Waiting for Prefect server..."
until curl -sf http://localhost:4200/api/health > /dev/null 2>&1; do
    sleep 2
done
echo "Prefect server ready."

# Enregistre les déploiements et démarre le serving
exec python -m flows.deployments
