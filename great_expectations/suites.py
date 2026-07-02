"""Suites d'expectations : déclaratives, en code, sans arborescence de projet GE.

Chaque suite est une liste de tuples (table, nom_expectation, colonne, kwargs)
qu'on dépaquète dans runner.py. Les garder comme données permet de les réutiliser
dans les tests unitaires.

Pourquoi GE en plus des tests dbt ?
    • Les tests dbt tournent sur les marts transformés. GE tourne sur la couche
      *raw* d'atterrissage : dès que les données arrivent, avant toute transformation.
    • GE détecte le schema drift, les anomalies de valeurs, les retards de fraîcheur
      AVANT qu'ils se propagent (et corrompent) les marts.
"""
from __future__ import annotations

# (table, expectation_type, colonne_ou_None, kwargs)
RAW_ACCOUNTS = [
    ("raw.accounts", "expect_table_row_count_to_be_between",   None, {"min_value": 100,  "max_value": 200_000}),
    ("raw.accounts", "expect_column_to_exist",                 "account_id", {}),
    ("raw.accounts", "expect_column_values_to_not_be_null",    "account_id", {}),
    ("raw.accounts", "expect_column_values_to_be_unique",      "account_id", {}),
    ("raw.accounts", "expect_column_values_to_be_in_set",      "plan",
        {"value_set": ["starter", "pro", "enterprise"]}),
    ("raw.accounts", "expect_column_values_to_be_in_set",      "acquisition_ch",
        {"value_set": ["paid", "organic", "referral", "outbound"]}),
    ("raw.accounts", "expect_column_values_to_be_between",     "seats",
        {"min_value": 1, "max_value": 100_000, "mostly": 0.99}),
    ("raw.accounts", "expect_column_values_to_not_be_null",    "signup_ts", {}),
]

RAW_SUBSCRIPTIONS = [
    ("raw.subscriptions", "expect_column_values_to_be_unique",      "subscription_id", {}),
    ("raw.subscriptions", "expect_column_values_to_not_be_null",    "account_id", {}),
    ("raw.subscriptions", "expect_column_values_to_be_between",     "mrr",
        {"min_value": 0, "max_value": 5_000_000}),
    ("raw.subscriptions", "expect_column_pair_values_a_to_be_greater_than_b",
        None, {"column_A": "valid_to", "column_B": "valid_from",
               "or_equal": True, "ignore_row_if": "either_value_is_missing"}),
]

RAW_INVOICES = [
    ("raw.invoices", "expect_column_values_to_be_unique",         "invoice_id", {}),
    ("raw.invoices", "expect_column_values_to_be_in_set",         "status",
        {"value_set": ["paid", "overdue", "failed", "refunded"]}),
    ("raw.invoices", "expect_column_values_to_be_between",        "amount",
        {"min_value": 0, "max_value": 5_000_000}),
]

RAW_EVENTS = [
    ("raw.events", "expect_column_values_to_be_unique",           "event_id", {}),
    ("raw.events", "expect_column_values_to_be_in_set",           "event_type",
        {"value_set": ["login", "feature_use", "export", "invite_user", "dashboard_view"]}),
]

RAW_TICKETS = [
    ("raw.tickets", "expect_column_values_to_be_unique",          "ticket_id", {}),
    ("raw.tickets", "expect_column_values_to_be_in_set",          "priority",
        {"value_set": ["low", "medium", "high", "urgent"]}),
    ("raw.tickets", "expect_column_values_to_be_between",         "csat",
        {"min_value": 1, "max_value": 5,
         "mostly": 0.99, "ignore_row_if": "all_values_are_missing"}),
]

ALL_SUITES = (
    RAW_ACCOUNTS + RAW_SUBSCRIPTIONS + RAW_INVOICES + RAW_EVENTS + RAW_TICKETS
)
