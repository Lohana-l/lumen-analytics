"""Job de prédiction batch : lit mart_account_health, écrit dans analytics.churn_predictions.

Chaque ligne embarque ses top-3 drivers SHAP, exposés ensuite par le
dashboard (drill-down compte) et l'API.
"""
from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from psycopg2.extras import execute_values

from ingestion.config import reporting_date, settings
from ingestion.db import engine, pg_conn
from ml.features import build_features, load_health
from ml.tiering import tiers_by_quantile


def _load_model(model_dir: Path):
    candidates = sorted(model_dir.glob("churn_*.pkl"))
    if not candidates:
        raise FileNotFoundError(f"Aucun modèle entraîné dans {model_dir} : lancer ml.train d'abord.")
    # XGB en priorité si les deux existent
    for c in candidates:
        if c.name.startswith("churn_xgb"):
            return pickle.loads(c.read_bytes()), c
    return pickle.loads(candidates[0].read_bytes()), candidates[0]


def _shap_for_predictions(bundle, X: pd.DataFrame, top_n: int = 3):
    """SHAP optionnel : ignoré pour logreg ou si shap n'est pas installé."""
    if bundle["model_name"] != "xgb":
        return [None] * len(X)
    try:
        from ml.shap_explain import explain_xgboost, top_drivers_per_row
        shap_values, _ = explain_xgboost(bundle["model"], X)
        return top_drivers_per_row(shap_values, X, top_n=top_n)
    except Exception as exc:
        logger.warning("SHAP indisponible : {}", exc)
        return [None] * len(X)


def run(model_dir: Path | None = None) -> pd.DataFrame:
    model_dir      = Path(model_dir or settings().model_dir)
    bundle, path   = _load_model(model_dir)
    logger.info("Modèle chargé : {} ({})", bundle["model_name"], path.name)

    health         = load_health(engine())
    # On ne score que les comptes ACTIFS : prédire le churn d'un compte déjà
    # parti n'a pas de sens, et leurs features post-churn (mrr=0, activité=0)
    # truqueraient le tiering par quantile en occupant les rangs critiques.
    health         = health[~health["is_churned"]].reset_index(drop=True)
    ff             = build_features(health, as_of=reporting_date())
    # alignement des colonnes sur le schéma d'entraînement (dummies manquants/extra)
    X              = ff.X.reindex(columns=bundle["feature_names"], fill_value=0)

    probs  = bundle["model"].predict_proba(X)[:, 1]
    # top_n=5 : assez pour que le drill-down SHAP du dashboard montre un vrai
    # profil de risque (3 barres faisaient maigre), sans gonfler le JSONB.
    drivers = _shap_for_predictions(bundle, X, top_n=5)

    out = pd.DataFrame({
        "account_id":        ff.meta["account_id"].values,
        "churn_risk_score":  np.round(probs * 100, 2),
        # Tiering par quantile partagé (ml.tiering) : même définition que la doc
        # et les seuils API, voir le module pour la justification.
        "churn_risk_tier":   tiers_by_quantile(probs),
        "model_name":        bundle["model_name"],
        "model_version":     bundle["model_version"],
        "top_drivers":       [json.dumps(d) if d else None for d in drivers],
    })

    # upsert dans analytics.churn_predictions (PK = account_id)
    with pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TEMP TABLE _stage_pred (LIKE analytics.churn_predictions
                                               INCLUDING ALL) ON COMMIT DROP;
            """)
            # execute_values : un seul aller-retour réseau pour tout le batch,
            # là où executemany émettrait un INSERT par ligne.
            execute_values(cur, """
                INSERT INTO _stage_pred
                    (account_id, churn_risk_score, churn_risk_tier,
                     model_name, model_version, top_drivers)
                VALUES %s;
            """, out.values.tolist(),
                template="(%s, %s, %s, %s, %s, %s::jsonb)")
            cur.execute("""
                INSERT INTO analytics.churn_predictions AS t
                    (account_id, churn_risk_score, churn_risk_tier,
                     model_name, model_version, top_drivers)
                SELECT account_id, churn_risk_score, churn_risk_tier,
                       model_name, model_version, top_drivers
                FROM _stage_pred
                ON CONFLICT (account_id) DO UPDATE SET
                    churn_risk_score = excluded.churn_risk_score,
                    churn_risk_tier  = excluded.churn_risk_tier,
                    model_name       = excluded.model_name,
                    model_version    = excluded.model_version,
                    top_drivers      = excluded.top_drivers,
                    predicted_at     = now();
            """)
        conn.commit()
    logger.success("{} prédictions écrites vers analytics.churn_predictions", len(out))
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Lance le batch de prédictions churn Cairn")
    p.add_argument("--model-dir", default=None)
    args = p.parse_args()
    run(model_dir=args.model_dir)


if __name__ == "__main__":
    main()
