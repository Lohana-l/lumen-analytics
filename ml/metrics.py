"""Métriques de classification retenues pour le churn.

L'accuracy est un piège sur des classes déséquilibrées. On suit :
    - ROC-AUC           (qualité du ranking)
    - PR-AUC  (average precision), plus pertinent sur données déséquilibrées
    - Brier score       (calibration des probabilités)
    - statistique KS    (mesure de séparation classique)
    - Precision @ top-k (métrique métier : "sur les 50 comptes les plus à risque,
                          combien ont vraiment churné ?")
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
)


def ks_statistic(y_true: np.ndarray, y_score: np.ndarray) -> float:
    order = np.argsort(-y_score)
    y     = np.asarray(y_true)[order]
    cum_pos = np.cumsum(y) / max(y.sum(), 1)
    cum_neg = np.cumsum(1 - y) / max((1 - y).sum(), 1)
    return float(np.max(np.abs(cum_pos - cum_neg)))


def precision_at_k(y_true: np.ndarray, y_score: np.ndarray, k: int) -> float:
    if k <= 0 or k > len(y_true):
        return 0.0
    order = np.argsort(-y_score)[:k]
    return float(np.asarray(y_true)[order].sum()) / k


def bootstrap_ci(
    y_true:  np.ndarray,
    y_score: np.ndarray,
    metric_fn,
    n_boot:  int = 1_000,
    alpha:   float = 0.05,
    seed:    int = 42,
) -> tuple[float, float]:
    """Intervalle de confiance bootstrap percentile pour une métrique de ranking.

    Indispensable ici : le jeu de test fait ~80 lignes avec ~8 churners, donc
    une AUC ponctuelle est très instable. L'IC rend cette incertitude visible
    au lieu de laisser un 0.97 isolé se faire passer pour de la robustesse.

    Les rééchantillons sans les deux classes sont ignorés (la métrique n'y est
    pas définie).
    """
    rng    = np.random.default_rng(seed)
    y_true = np.asarray(y_true)
    y_score = np.asarray(y_score)
    n      = len(y_true)
    stats: list[float] = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        yt  = y_true[idx]
        if yt.min() == yt.max():        # une seule classe : métrique non définie
            continue
        stats.append(float(metric_fn(yt, y_score[idx])))
    if not stats:
        return float("nan"), float("nan")
    lo, hi = np.percentile(stats, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(lo), float(hi)


def full_report(y_true: np.ndarray, y_score: np.ndarray) -> dict[str, float]:
    y_true = np.asarray(y_true)
    roc_lo, roc_hi = bootstrap_ci(y_true, y_score, roc_auc_score)
    pr_lo,  pr_hi  = bootstrap_ci(y_true, y_score, average_precision_score)
    return {
        "roc_auc":          float(roc_auc_score(y_true, y_score)),
        "roc_auc_ci_low":   roc_lo,
        "roc_auc_ci_high":  roc_hi,
        "pr_auc":           float(average_precision_score(y_true, y_score)),
        "pr_auc_ci_low":    pr_lo,
        "pr_auc_ci_high":   pr_hi,
        "brier":            float(brier_score_loss(y_true, y_score)),
        "ks":               ks_statistic(y_true, y_score),
        "precision_at_50":  precision_at_k(y_true, y_score, 50),
        "precision_at_100": precision_at_k(y_true, y_score, 100),
        "base_rate":        float(y_true.mean()),
        "n":                int(len(y_true)),
    }


def compare_reports(*reports: tuple[str, dict[str, float]]) -> pd.DataFrame:
    """Comparaison côte à côte prête à afficher. Accepte des tuples ('nom', report)."""
    rows = [{"model": name, **r} for name, r in reports]
    return pd.DataFrame(rows).set_index("model")
