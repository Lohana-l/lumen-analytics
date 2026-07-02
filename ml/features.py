"""Feature engineering pour le modèle de churn.

Source unique : ``marts.mart_account_health``, la vue canonique sur laquelle
s'accordent tous les consommateurs aval (Streamlit, ML, FastAPI, Evidently).

Définition du label
-------------------
Classe positive (y=1) : compte churné dans la fenêtre
  (reporting_date - CHURN_HORIZON_DAYS, reporting_date]

Classe négative (y=0) : compte actif sur toute la fenêtre.

La coupure d'entraînement est reporting_date - CHURN_HORIZON_DAYS ; on
n'utilise que les features connues à cette date pour éviter le target leakage.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
from sqlalchemy.engine import Engine

FEATURE_COLUMNS: list[str] = [
    "mrr",
    "tenure_months",
    "days_since_signup",
    "current_seats",
    "events_30d",
    "dau_30d_distinct",
    "active_days_30d",
    "stickiness_30d",
    "invoices_paid_count",
    "invoices_overdue_count",
    "invoices_failed_count",
    "tickets_90d",
    "urgent_tickets_90d",
]
LABEL_COLUMN: str = "is_churned"

# groupes one-hot encodés avant entraînement
CATEGORICAL_COLUMNS: list[str] = ["current_plan", "acquisition_channel", "industry"]

# Fenêtre de label : un compte est positif s'il churn dans les HORIZON jours
# APRÈS la coupure d'entraînement (cut = reporting_date - HORIZON). 180 jours
# pour garder assez de positifs (~3-4% de taux de base sur la seed).
# DOIT rester aligné avec l'interval '180 days' de dbt/models/marts/mart_ml_training.sql
CHURN_HORIZON_DAYS = 180


@dataclass(frozen=True)
class FeatureFrame:
    """Bundle renvoyé par build_features (X, y, métadonnées)."""
    X:       pd.DataFrame
    y:       pd.Series
    meta:    pd.DataFrame     # conserve account_id + industry pour slicing post-hoc
    as_of:   date


# ----------------------------------------------------------------------
# I/O
# ----------------------------------------------------------------------
def load_health(engine: Engine) -> pd.DataFrame:
    """Charge la table mart_account_health complète en mémoire.

    Photo des comptes à reporting_date : c'est la table de SERVING
    (ml.predict score l'état courant). Ne pas l'utiliser pour entraîner :
    les churners y figurent post-churn (mrr=0, activité=0), donc target leakage.
    """
    return pd.read_sql("SELECT * FROM marts.mart_account_health", engine)


def load_training(engine: Engine) -> pd.DataFrame:
    """Charge mart_ml_training : features point-in-time pour l'ENTRAÎNEMENT.

    Chaque compte est photographié à sa date de coupure (veille du churn pour
    les churners, reporting_date pour les actifs), si bien que le modèle
    apprend les précurseurs du churn et non ses conséquences.
    """
    return pd.read_sql("SELECT * FROM marts.mart_ml_training", engine)


# ----------------------------------------------------------------------
# Encodage
# ----------------------------------------------------------------------
def encode(df: pd.DataFrame) -> pd.DataFrame:
    """One-hot encode les features catégorielles. Renvoie un DataFrame numérique."""
    out = df.copy()
    for col in CATEGORICAL_COLUMNS:
        if col in out.columns:
            dummies = pd.get_dummies(out[col], prefix=col, dummy_na=False)
            out = pd.concat([out.drop(columns=[col]), dummies], axis=1)
    return out


def build_features(
    df: pd.DataFrame,
    as_of: date,
    horizon_days: int = CHURN_HORIZON_DAYS,
) -> FeatureFrame:
    """Renvoie une paire (X, y) prête pour sklearn / XGBoost.

    Parameters
    ----------
    df : pandas.DataFrame
        Sortie de ``load_health``.
    as_of : date
        Date de coupure des features : on n'utilise que les features à cette date.
        Le label regarde en avant jusqu'à ``horizon_days`` jours.
    horizon_days : int
        Longueur de la fenêtre de churn. Par défaut = 90.
    """
    train   = df.copy()
    # NaN numériques mis à 0 (événements manquants = zéro événements)
    for c in FEATURE_COLUMNS:
        if c in train.columns:
            train[c] = train[c].fillna(0)

    train = encode(train)

    y    = train[LABEL_COLUMN].astype(int)
    meta = df[["account_id", "industry", "current_plan", "country"]].copy()

    # on garde seulement les colonnes features numériques (tout sauf identifiants + label)
    drop_cols = {
        "account_id", "company_name", "country", "last_event_ts",
        "signup_ts", "churned_ts", LABEL_COLUMN, "rule_based_health_score",
        "avg_csat_90d", "as_of_date",
    }
    X = train.drop(columns=[c for c in drop_cols if c in train.columns])
    # bool dummies convertis en int pour XGBoost
    X = X.astype({c: "float32" for c in X.select_dtypes("bool").columns})

    return FeatureFrame(X=X, y=y, meta=meta, as_of=as_of)


def train_test_split_by_date(
    ff: FeatureFrame, holdout_frac: float = 0.2, seed: int = 42
) -> tuple[FeatureFrame, FeatureFrame]:
    """Split stratifié sur y : le holdout reste représentatif des événements rares."""
    from sklearn.model_selection import train_test_split as _tts

    X_tr, X_te, y_tr, y_te, m_tr, m_te = _tts(
        ff.X, ff.y, ff.meta,
        test_size=holdout_frac, random_state=seed, stratify=ff.y,
    )
    return (
        FeatureFrame(X=X_tr, y=y_tr, meta=m_tr, as_of=ff.as_of),
        FeatureFrame(X=X_te, y=y_te, meta=m_te, as_of=ff.as_of),
    )
