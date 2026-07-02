"""Génère les rapports HTML Evidently pour le drift et la performance modèle.

On compare la distribution *courante* des features à une fenêtre de *référence*
(les 90 jours précédant CHURN_HORIZON_DAYS avant la reporting_date) -
la même période sur laquelle le modèle a été entraîné.

Sorties (servies par l'onglet Monitoring de Streamlit) :
    data/evidently_reports/data_drift.html
    data/evidently_reports/target_drift.html
    data/evidently_reports/model_performance.html
    data/evidently_reports/summary.json
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from ingestion.config import reporting_date
from ingestion.db import engine
from ml.features import FEATURE_COLUMNS

OUT_DIR = Path("data/evidently_reports")


def _load_health() -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM marts.mart_account_health", engine())


def _load_training() -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM marts.mart_ml_training", engine())


def _psi(ref: pd.Series, cur: pd.Series, bins: int = 10) -> float:
    """Population Stability Index RÉEL entre deux distributions.

    Binning par déciles de la RÉFÉRENCE (standard industrie), bornes ±inf
    pour capturer les valeurs hors plage, plancher 1e-4 pour éviter log(0).
    Lecture : < 0.10 stable, 0.10-0.20 à surveiller, >= 0.20 drift critique.
    """
    ref = pd.to_numeric(ref, errors="coerce").dropna().astype(float)
    cur = pd.to_numeric(cur, errors="coerce").dropna().astype(float)
    if ref.empty or cur.empty:
        return 0.0
    qs = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(qs) < 3:                       # variable quasi constante en référence
        qs = np.array([qs[0] - 0.5, qs[0], qs[-1] + 0.5])
    edges = np.concatenate(([-np.inf], qs[1:-1], [np.inf]))
    r = np.histogram(ref, bins=edges)[0] / len(ref)
    c = np.histogram(cur, bins=edges)[0] / len(cur)
    r = np.clip(r, 1e-4, None)
    c = np.clip(c, 1e-4, None)
    return float(np.sum((c - r) * np.log(c / r)))


def _load_predictions() -> pd.DataFrame:
    try:
        return pd.read_sql(
            "SELECT account_id, churn_risk_score / 100.0 AS prediction "
            "FROM analytics.churn_predictions", engine())
    except Exception:
        return pd.DataFrame(columns=["account_id", "prediction"])


def _split_reference_current(as_of: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Référence vs courant : la définition canonique du drift de serving.

        référence = mart_ml_training        (distribution d'ENTRAÎNEMENT,
                                             features point-in-time)
        courant   = mart_account_health     (population réellement SCORÉE :
                                             comptes actifs à reporting_date)

    C'est la comparaison qui répond à la question du monitoring : « la
    population que le modèle score aujourd'hui ressemble-t-elle encore à
    celle sur laquelle il a appris ? ». Comparer deux tranches du même
    snapshot (l'ancien proxy par tenure) mélangeait les churners post-churn
    (mrr=0) dans la référence et fabriquait un drift artificiel géant sur mrr.
    """
    ref = _load_training()
    cur = _load_health()
    cur = cur[~cur["is_churned"]].copy()
    logger.info("référence = {:,} (training)  courant = {:,} (actifs scorés)",
                len(ref), len(cur))
    return ref, cur


def run() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # on essaie le vrai import Evidently ; fallback JSON-only si absent
    try:
        from evidently.metric_preset import (
            ClassificationPreset,
            DataDriftPreset,
            TargetDriftPreset,
        )
        from evidently.report import Report
        real_evidently = True
    except ModuleNotFoundError:
        logger.warning("Evidently non installé : écriture du résumé JSON uniquement.")
        real_evidently = False

    ref, cur = _split_reference_current(reporting_date())
    preds    = _load_predictions()
    if preds.empty:
        logger.warning("Pas encore de prédictions : rapports target/performance ignorés.")
    else:
        cur = cur.merge(preds, on="account_id", how="left")

    # Les features qui DÉFINISSENT le split référence/courant (la tenure) sont
    # exclues de la comparaison : leur "drift" mesurerait le critère de
    # découpage lui-même, pas un changement du monde. Les garder afficherait
    # un PSI critique permanent et noierait les vrais signaux.
    split_features = {"tenure_months", "days_since_signup"}
    feat_cols = [c for c in FEATURE_COLUMNS
                 if c in ref.columns and c not in split_features]
    ref_X = ref[feat_cols].copy()
    cur_X = cur[feat_cols].copy()

    if real_evidently:
        drift_report = Report(metrics=[DataDriftPreset()])
        drift_report.run(reference_data=ref_X, current_data=cur_X)
        drift_report.save_html(str(OUT_DIR / "data_drift.html"))

        # Target drift : taux de churn observé à l'entraînement vs taux de
        # churn PRÉDIT sur la population courante (les actifs n'ont pas encore
        # de label ; la prédiction binarisée à 0.5 sert de proxy de cible).
        if "prediction" in cur.columns and cur["prediction"].notna().any():
            tgt_ref = ref[["is_churned"]].astype(int).rename(columns={"is_churned": "target"})
            tgt_cur = (cur["prediction"].fillna(0) >= 0.5).astype(int).to_frame("target")
            target_report = Report(metrics=[TargetDriftPreset()])
            target_report.run(
                reference_data=tgt_ref.assign(**ref_X),
                current_data=tgt_cur.assign(**cur_X),
                column_mapping=None,
            )
            target_report.save_html(str(OUT_DIR / "target_drift.html"))

        # Performance modèle : nécessite une vérité terrain sur la population
        # courante. Les comptes actifs n'en ont pas (le churn futur n'est pas
        # encore observé), rapport ignoré tant qu'aucun label ne tombe.
        if "is_churned" in cur.columns and cur["is_churned"].nunique() > 1 \
                and "prediction" in cur.columns and cur["prediction"].notna().any():
            perf_ref = ref.assign(
                target=ref["is_churned"].astype(int),
                prediction=ref["is_churned"].astype(int),   # référence = labels d'entraînement
            )[["target", "prediction", *feat_cols]].dropna()
            perf_cur = cur.assign(
                target=cur["is_churned"].astype(int),
                prediction=(cur["prediction"].fillna(0) >= 0.5).astype(int),
            )[["target", "prediction", *feat_cols]].dropna()
            if len(perf_ref) > 0 and len(perf_cur) > 0:
                perf_report = Report(metrics=[ClassificationPreset()])
                perf_report.run(reference_data=perf_ref, current_data=perf_cur)
                perf_report.save_html(str(OUT_DIR / "model_performance.html"))

    # résumé JSON toujours écrit (PSI réel + magnitudes de drift + taux de base)
    summary = {
        "as_of":     str(reporting_date()),
        "reference_n":  int(len(ref)),
        "current_n":    int(len(cur)),
        # PSI RÉEL par feature (déciles de la référence). C'est la valeur que
        # la page Monitoring affiche ; l'ancien proxy |mean_shift|/constante
        # était insensible à l'échelle réelle des variables (un mrr moyen à
        # 20 k€ saturait la jauge à 1.5 pour un shift de quelques centaines d'€).
        "feature_psi": {
            c: round(_psi(ref_X[c], cur_X[c]), 4)
            for c in feat_cols
        },
        "feature_mean_shift": {
            c: float(cur_X[c].mean() - ref_X[c].mean())
            for c in feat_cols
        },
        "reference_churn_rate": float(ref["is_churned"].mean()) if "is_churned" in ref else None,
        # population courante = comptes actifs, pas encore de label : on expose
        # le taux de churn PRÉDIT (score binarisé à 0.5) comme proxy
        "current_churn_rate":   (
            float((cur["prediction"].fillna(0) >= 0.5).mean())
            if "prediction" in cur.columns else None
        ),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    logger.success("Rapports Evidently : {}", OUT_DIR)


if __name__ == "__main__":
    run()
