"""Tiering du risque de churn : la définition unique, partagée API et batch.

Deux granularités, un seul module, pour qu'aucun consommateur ne réinvente
sa propre échelle :

- `tiers_by_quantile` : attribution par RANG dans le portefeuille complet.
  C'est la convention CSM (Gainsight, ChurnZero) : le dashboard surface
  toujours les "top N comptes à appeler", indépendamment de la calibration
  absolue du modèle. Utilisée par le batch ml.predict, qui voit tout le
  portefeuille.

- `tier_from_probability` : seuils absolus, pour les appels unitaires de
  l'API où le contexte portefeuille n'existe pas. Les seuils (0.75 / 0.50 /
  0.25) sont calibrés pour approcher les coupes quantiles sur le dataset de
  référence ; une probabilité isolée ne peut pas être rangée par quantile.

Conséquence assumée : un même compte peut différer d'un tier entre une
prédiction unitaire API et le batch (calibration vs rang). Si la cohérence
stricte importe, consommer analytics.churn_predictions (le batch), qui est
la source de vérité du dashboard.
"""
from __future__ import annotations

import numpy as np

# Seuils absolus (probabilité de churn) pour le scoring unitaire.
TIER_THRESHOLDS: list[tuple[float, str]] = [
    (0.75, "critical"),
    (0.50, "high"),
    (0.25, "medium"),
]

# Coupes par rang (part du portefeuille) pour le scoring batch.
QUANTILE_CUTS: list[tuple[float, str]] = [
    (0.05, "critical"),   # top 5 %
    (0.15, "high"),       # 6-15 %
    (0.30, "medium"),     # 16-30 %
]


def tier_from_probability(prob: float) -> str:
    """Tier par seuil absolu : pour une prédiction isolée (API unitaire)."""
    for threshold, tier in TIER_THRESHOLDS:
        if prob >= threshold:
            return tier
    return "low"


def tiers_by_quantile(probs: np.ndarray) -> list[str]:
    """Tiers par rang dans le portefeuille : pour le batch complet.

    Top 5 % -> critical, 6-15 % -> high, 16-30 % -> medium, reste -> low.
    """
    n = len(probs)
    if n == 0:
        return []
    # rang descendant : 0 = score le plus haut
    order = np.argsort(-np.asarray(probs))
    rank = np.empty(n, dtype=int)
    rank[order] = np.arange(n)
    pct = rank / max(n - 1, 1)   # 0.0 = top, 1.0 = bottom

    tiers: list[str] = []
    for i in range(n):
        for cut, tier in QUANTILE_CUTS:
            if pct[i] < cut:
                tiers.append(tier)
                break
        else:
            tiers.append("low")
    return tiers
