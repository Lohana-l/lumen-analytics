"""Lance toutes les expectations GE contre Postgres, écrit un JSON résumé + code de retour.

Conçu pour être appelé depuis Prefect (et depuis le job d'intégration GitHub Actions).
Renvoie le code 0 si toutes les expectations passent, 1 sinon.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from loguru import logger

from great_expectations.suites import ALL_SUITES
from ingestion.db import engine

OUT_DIR = Path("data/ge_reports")


def _check_one(table: str, expectation: str, column: str | None, kwargs: dict) -> dict:
    """Implémentation Python légère qui reproduit la sémantique de GE.

    On n'embarque pas le moteur GE complet pour garder les tests unitaires rapides
    et sans checkpoint store. La vraie librairie GE reste dans requirements-ml.txt
    pour les utilisateurs qui veulent les validation_results dans DataDocs.
    """
    eng = engine()
    df  = pd.read_sql(f"SELECT * FROM {table}", eng)
    n   = len(df)

    def _pass(success: bool, observed: dict | None = None) -> dict:
        return {"table": table, "expectation": expectation,
                "column": column, "success": success,
                "observed": observed or {}, "n": n}

    if expectation == "expect_table_row_count_to_be_between":
        ok = kwargs["min_value"] <= n <= kwargs["max_value"]
        return _pass(ok, {"row_count": n})

    if column is None and expectation != "expect_column_pair_values_a_to_be_greater_than_b":
        return _pass(False, {"error": "missing column"})

    if expectation == "expect_column_to_exist":
        return _pass(column in df.columns)

    if expectation == "expect_column_values_to_not_be_null":
        nulls = int(df[column].isna().sum())
        return _pass(nulls == 0, {"null_count": nulls})

    if expectation == "expect_column_values_to_be_unique":
        dup   = int(df[column].duplicated().sum())
        return _pass(dup == 0, {"duplicate_count": dup})

    if expectation == "expect_column_values_to_be_in_set":
        bad = df[~df[column].isin(kwargs["value_set"])]
        return _pass(len(bad) == 0, {"unexpected_count": len(bad)})

    if expectation == "expect_column_values_to_be_between":
        col   = pd.to_numeric(df[column], errors="coerce")
        if kwargs.get("ignore_row_if") == "all_values_are_missing":
            col = col.dropna()
        bad = col[(col < kwargs["min_value"]) | (col > kwargs["max_value"])]
        ratio = 1 - len(bad) / max(len(col), 1)
        mostly = kwargs.get("mostly", 1.0)
        return _pass(ratio >= mostly, {"unexpected_count": int(len(bad)),
                                       "pass_ratio": round(ratio, 4)})

    if expectation == "expect_column_pair_values_a_to_be_greater_than_b":
        a, b = kwargs["column_A"], kwargs["column_B"]
        sub = df.dropna(subset=[a, b]) if kwargs.get("ignore_row_if") else df
        cmp = sub[a] >= sub[b] if kwargs.get("or_equal") else sub[a] > sub[b]
        return _pass(bool(cmp.all()), {"violations": int((~cmp).sum())})

    return _pass(False, {"error": f"expectation inconnue : {expectation}"})


def run() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    failed  = 0
    for table, expectation, column, kwargs in ALL_SUITES:
        try:
            r = _check_one(table, expectation, column, kwargs)
        except Exception as exc:
            r = {"table": table, "expectation": expectation, "column": column,
                 "success": False, "observed": {"error": str(exc)}}
        results.append(r)
        if not r["success"]:
            failed += 1
            logger.warning("✗ {} :: {} {}", table, expectation, column or "")

    summary = {"total": len(results), "failed": failed,
               "passed": len(results) - failed, "results": results}
    out = OUT_DIR / "ge_summary.json"
    out.write_text(json.dumps(summary, indent=2))
    logger.info("Résumé GE : {} ({} pass, {} fail)", out,
                summary["passed"], summary["failed"])
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
