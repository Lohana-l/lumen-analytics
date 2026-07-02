"""Entraînement : baseline LogReg + challenger XGBoost.

Tout est tracé dans MLflow :
  - params  (classe du modèle, hyperparamètres)
  - metrics (roc_auc, pr_auc, brier, ks, precision@50/100)
  - artifacts (modèle + SHAP summary plot + metrics.json)

La logique de promotion en production vit dans le MLflow Model Registry
(``cairn-churn``, stage ``Production``), qui tient ici lieu de
processus de gouvernance simplifié.

Usage (dans le conteneur pipeline) :
    python -m ml.train                     # entraîne les deux, compare, enregistre le meilleur
    python -m ml.train --model xgb         # challenger XGB uniquement
    python -m ml.train --no-mlflow         # sans MLflow (chemin rapide CI)
"""
from __future__ import annotations

import argparse
import json
import pickle
from datetime import date
from pathlib import Path

from loguru import logger
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ingestion.config import reporting_date, settings
from ingestion.db import engine
from ml import metrics as M
from ml.features import (
    build_features,
    load_training,
    train_test_split_by_date,
)

# MLflow optionnel : désactivé proprement en CI sans serveur de tracking
try:
    import mlflow
    import mlflow.sklearn
    import mlflow.xgboost
    _HAS_MLFLOW = True
except ModuleNotFoundError:
    _HAS_MLFLOW = False


# ----------------------------------------------------------------------
# Constructeurs de modèles
# ----------------------------------------------------------------------
def build_logreg() -> Pipeline:
    """Baseline : features standardisées + LogReg avec class-weight balancing.

    Le class_weight="balanced" est la réponse la plus simple et défendable
    à un target déséquilibré (≈8% churn). On évite l'over/undersampling
    qui complique la validation.
    """
    return Pipeline([
        ("scaler", StandardScaler(with_mean=False)),
        ("clf",    LogisticRegression(
            class_weight="balanced",
            max_iter=1_000,
            solver="lbfgs",
        )),
    ])


def build_xgb(scale_pos_weight: float = 11.0):
    """Challenger XGBoost, volontairement contraint en capacité.

    max_depth=4 / min_child_weight=5 / 300 arbres : sur ~1 800 lignes, un
    modèle plus profond mémorise ses négatifs et écrase toutes les
    probabilités vers 0 - exactement le symptôme qu'on veut éviter au
    serving. scale_pos_weight est calculé depuis le taux de base RÉEL du
    train (≈ (1-p)/p), pas une constante figée.
    """
    import xgboost as xgb  # import différé
    return xgb.XGBClassifier(
        n_estimators=300,
        max_depth=4,
        min_child_weight=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="binary:logistic",
        eval_metric="aucpr",
        tree_method="hist",
        scale_pos_weight=scale_pos_weight,
        random_state=42,
    )


# ----------------------------------------------------------------------
# Entraînement + évaluation d'un modèle
# ----------------------------------------------------------------------
def fit_and_score(name: str, model, train, test) -> dict:
    model.fit(train.X, train.y)
    scores = model.predict_proba(test.X)[:, 1]
    report = M.full_report(test.y.to_numpy(), scores)
    logger.info("{:<8} | AUC={:.3f} [IC95 {:.3f}-{:.3f}] PR-AUC={:.3f} KS={:.3f} P@50={:.2f}",
                name, report["roc_auc"], report["roc_auc_ci_low"],
                report["roc_auc_ci_high"], report["pr_auc"],
                report["ks"], report["precision_at_50"])
    return {"name": name, "model": model, "report": report,
            "scores": scores}


# ----------------------------------------------------------------------
# Point d'entrée principal
# ----------------------------------------------------------------------
def run(
    model_choice: str = "both",
    use_mlflow:   bool = True,
    model_dir:    Path | None = None,
) -> dict:
    model_dir = Path(model_dir or settings().model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Chargement de mart_ml_training (features point-in-time)…")
    health = load_training(engine())
    logger.info("  {} lignes (taux de base = {:.2%})", len(health),
                health["is_churned"].mean())

    ff = build_features(health, as_of=reporting_date())
    train, test = train_test_split_by_date(ff)
    logger.info("  train = {}   test = {}", len(train.X), len(test.X))

    # correction du déséquilibre dérivée du taux de base réel du train
    base_rate = float(train.y.mean())
    spw       = (1 - base_rate) / max(base_rate, 1e-6)
    logger.info("  scale_pos_weight = {:.1f} (taux de base train = {:.2%})", spw, base_rate)

    results = []
    if model_choice in ("logreg", "both"):
        results.append(fit_and_score("logreg", build_logreg(),                     train, test))
    if model_choice in ("xgb", "both"):
        results.append(fit_and_score("xgb",    build_xgb(scale_pos_weight=spw),    train, test))

    results.sort(key=lambda r: -r["report"]["pr_auc"])
    winner = results[0]
    logger.success("Gagnant : {} (PR-AUC={:.3f})", winner["name"], winner["report"]["pr_auc"])

    # --- persistance ---
    # Version dérivée de la date d'entraînement : traçable sans registre,
    # cohérente entre le pickle, l'API (/model/info) et le dashboard.
    model_version = date.today().strftime("%Y.%m.%d")
    model_path = model_dir / f"churn_{winner['name']}.pkl"
    with open(model_path, "wb") as f:
        pickle.dump({
            "model":          winner["model"],
            "feature_names":  list(train.X.columns),
            "model_name":     winner["name"],
            "model_version":  model_version,
            "base_rate":      float(ff.y.mean()),
            "trained_at":     str(date.today()),
        }, f)
    logger.info("  modèle écrit vers {}", model_path)

    metrics_path = model_dir / "latest_metrics.json"
    metrics_path.write_text(json.dumps(
        {r["name"]: r["report"] for r in results}, indent=2
    ))

    # --- tracking MLflow (optionnel, ignoré proprement si indisponible) ---
    if use_mlflow and _HAS_MLFLOW:
        mlflow.set_tracking_uri(settings().mlflow_tracking_uri)
        mlflow.set_experiment(settings().mlflow_experiment)
        for r in results:
            with mlflow.start_run(run_name=r["name"]):
                mlflow.log_params({"model_class": r["name"]})
                mlflow.log_metrics(r["report"])
                if r["name"] == "xgb":
                    # Enregistre le modèle xgboost dans le Model Registry et le
                    # promeut en Production. Le registry sert d'audit trail
                    # (lignage, stages, historique) ; le serving, lui, reste sur
                    # le pickle local par choix assumé : pas de dépendance réseau
                    # sur le chemin d'inférence (voir README, Limitations).
                    mlflow.xgboost.log_model(
                        r["model"], "model",
                        registered_model_name="xgboost_churn_model",
                    )
                    try:
                        from mlflow.tracking import MlflowClient
                        client = MlflowClient(settings().mlflow_tracking_uri)
                        latest = max(
                            client.search_model_versions("name='xgboost_churn_model'"),
                            key=lambda v: int(v.version),
                        )
                        client.transition_model_version_stage(
                            name="xgboost_churn_model",
                            version=latest.version,
                            stage="Production",
                            archive_existing_versions=True,
                        )
                        logger.info("  modèle promu en Production (v{})", latest.version)
                    except Exception as exc:
                        logger.warning("  promotion Production ignorée : {}", exc)
                else:
                    mlflow.sklearn.log_model(r["model"], "model")
        logger.info("  loggé dans MLflow : {}", settings().mlflow_tracking_uri)
    elif use_mlflow:
        logger.warning("  MLflow indisponible (import échoué), tracking ignoré")

    return {"winner": winner["name"], "path": str(model_path),
            "metrics": {r["name"]: r["report"] for r in results}}


def main() -> None:
    p = argparse.ArgumentParser(description="Entraîne le modèle de churn Cairn")
    p.add_argument("--model",     choices=["logreg", "xgb", "both"], default="both")
    p.add_argument("--no-mlflow", action="store_true")
    p.add_argument("--model-dir", default=None)
    args = p.parse_args()

    run(model_choice=args.model, use_mlflow=not args.no_mlflow,
        model_dir=args.model_dir)


if __name__ == "__main__":
    main()
