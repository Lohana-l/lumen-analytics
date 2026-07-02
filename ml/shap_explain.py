"""Explicabilité SHAP : importance globale + top drivers par prédiction.

Les valeurs SHAP répondent à la vraie question du customer success manager :
    "Pourquoi le compte X est-il à 83% de risque de churn ?"

On stocke les 3 principales contributions de features avec chaque prédiction
pour les exposer dans Streamlit et dans la réponse FastAPI ``/predict/churn``.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def global_importance(shap_values: np.ndarray, feature_names: list[str]) -> pd.DataFrame:
    """Valeur SHAP absolue moyenne par feature : classement d'importance globale."""
    mean_abs = np.abs(shap_values).mean(axis=0)
    return (
        pd.DataFrame({"feature": feature_names, "mean_abs_shap": mean_abs})
        .sort_values("mean_abs_shap", ascending=False)
        .reset_index(drop=True)
    )


def top_drivers_per_row(
    shap_values: np.ndarray,
    X:           pd.DataFrame,
    top_n:       int = 3,
) -> list[list[dict[str, Any]]]:
    """Pour chaque ligne, renvoie les top-N contributeurs SHAP avec signe et valeur."""
    cols    = list(X.columns)
    results: list[list[dict[str, Any]]] = []
    for i in range(shap_values.shape[0]):
        row  = shap_values[i]
        idx  = np.argsort(-np.abs(row))[:top_n]
        item = [
            {
                "feature":     cols[j],
                "value":       float(X.iloc[i, j]) if hasattr(X.iloc[i, j], "__float__") else X.iloc[i, j],
                "shap":        float(row[j]),
                "direction":   "↑ risk" if row[j] > 0 else "↓ risk",
            }
            for j in idx
        ]
        results.append(item)
    return results


def explain_xgboost(model, X: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """TreeExplainer SHAP : rapide et exact pour les modèles en arbres.

    Renvoie (shap_values, feature_names).
    """
    import shap  # import différé : dépendance lourde, seulement ici

    explainer = shap.TreeExplainer(model)
    values    = explainer.shap_values(X)
    # XGB en classification binaire renvoie un seul tableau 2D
    if isinstance(values, list) and len(values) == 2:
        values = values[1]
    return np.asarray(values), list(X.columns)
