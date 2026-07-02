-- ========================================================================
-- Cairn Analytics - raw schema
-- ------------------------------------------------------------------------
-- Exécuté une seule fois au premier démarrage du container Postgres via
-- /docker-entrypoint-initdb.d/01-init.sql. Maintient la couche raw proche
-- de ce qu'exposerait un vrai système source B2B SaaS (loaders idempotents,
-- clés naturelles, colonnes d'audit created_at).
-- ========================================================================

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;       -- dbt matérialise les vues ici
CREATE SCHEMA IF NOT EXISTS marts;         -- dbt matérialise les tables ici
CREATE SCHEMA IF NOT EXISTS analytics;     -- prédictions ML, Evidently, audit

COMMENT ON SCHEMA raw       IS 'Untransformed landing area - mirrors OLTP sources.';
COMMENT ON SCHEMA staging   IS 'dbt staging (views) - typed, renamed, deduped.';
COMMENT ON SCHEMA marts     IS 'dbt marts (tables) - star schema for BI + ML.';
COMMENT ON SCHEMA analytics IS 'ML output, drift reports, audit logs.';

-- ------------------------------------------------------------------------
-- Comptes (une ligne par organisation cliente, clé naturelle = account_id)
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.accounts (
    account_id      TEXT        PRIMARY KEY,
    company_name    TEXT        NOT NULL,
    industry        TEXT        NOT NULL,
    country         TEXT        NOT NULL,
    plan            TEXT        NOT NULL,        -- starter / pro / enterprise
    seats           INT         NOT NULL,
    signup_ts       TIMESTAMPTZ NOT NULL,
    churned_ts      TIMESTAMPTZ,
    acquisition_ch  TEXT        NOT NULL,        -- organic / paid / referral / outbound
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS raw_accounts_signup_idx  ON raw.accounts (signup_ts);
CREATE INDEX IF NOT EXISTS raw_accounts_plan_idx    ON raw.accounts (plan);

-- ------------------------------------------------------------------------
-- Abonnements (une ligne par changement de plan/seats - source des mouvements MRR)
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.subscriptions (
    subscription_id TEXT        PRIMARY KEY,
    account_id      TEXT        NOT NULL REFERENCES raw.accounts(account_id),
    plan            TEXT        NOT NULL,
    seats           INT         NOT NULL,
    mrr             NUMERIC(12, 2) NOT NULL,
    valid_from      TIMESTAMPTZ NOT NULL,
    valid_to        TIMESTAMPTZ,                 -- NULL = abonnement en cours
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS raw_subs_account_idx  ON raw.subscriptions (account_id);
CREATE INDEX IF NOT EXISTS raw_subs_valid_idx    ON raw.subscriptions (valid_from, valid_to);

-- ------------------------------------------------------------------------
-- Factures (une ligne par cycle de facturation)
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.invoices (
    invoice_id      TEXT        PRIMARY KEY,
    account_id      TEXT        NOT NULL REFERENCES raw.accounts(account_id),
    amount          NUMERIC(12, 2) NOT NULL,
    issued_ts       TIMESTAMPTZ NOT NULL,
    paid_ts         TIMESTAMPTZ,
    status          TEXT        NOT NULL,        -- paid / overdue / failed / refunded
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS raw_inv_account_idx  ON raw.invoices (account_id);
CREATE INDEX IF NOT EXISTS raw_inv_issued_idx   ON raw.invoices (issued_ts);

-- ------------------------------------------------------------------------
-- Événements produit (login, usage feature, export) - table de faits pour l'engagement
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.events (
    event_id        TEXT        PRIMARY KEY,
    account_id      TEXT        NOT NULL REFERENCES raw.accounts(account_id),
    user_id         TEXT        NOT NULL,
    event_type      TEXT        NOT NULL,
    event_ts        TIMESTAMPTZ NOT NULL,
    properties      JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS raw_events_account_idx  ON raw.events (account_id);
CREATE INDEX IF NOT EXISTS raw_events_ts_idx       ON raw.events (event_ts);
CREATE INDEX IF NOT EXISTS raw_events_type_idx     ON raw.events (event_type);

-- ------------------------------------------------------------------------
-- Tickets support (volume + ancienneté sont de forts signaux de churn)
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.tickets (
    ticket_id       TEXT        PRIMARY KEY,
    account_id      TEXT        NOT NULL REFERENCES raw.accounts(account_id),
    category        TEXT        NOT NULL,
    opened_ts       TIMESTAMPTZ NOT NULL,
    closed_ts       TIMESTAMPTZ,
    priority        TEXT        NOT NULL,        -- low / medium / high / urgent
    csat            INT,                         -- 1..5, NULL si non noté
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS raw_tkt_account_idx  ON raw.tickets (account_id);
CREATE INDEX IF NOT EXISTS raw_tkt_opened_idx   ON raw.tickets (opened_ts);

-- ------------------------------------------------------------------------
-- Table d'atterrissage des prédictions ML (alimentée par ml/predict.py + FastAPI)
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analytics.churn_predictions (
    account_id          TEXT        PRIMARY KEY,
    churn_risk_score    NUMERIC(5, 2) NOT NULL,        -- 0..100
    churn_risk_tier     TEXT          NOT NULL,        -- low / medium / high / critical
    model_name          TEXT          NOT NULL,
    model_version       TEXT          NOT NULL,
    top_drivers         JSONB,                          -- top 3 features SHAP
    predicted_at        TIMESTAMPTZ   NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------------
-- Log d'audit - qui/quoi/quand (utilisé par l'API + Streamlit + CI)
-- ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analytics.audit_log (
    audit_id        BIGSERIAL   PRIMARY KEY,
    actor           TEXT        NOT NULL,              -- email utilisateur ou nom du service
    action          TEXT        NOT NULL,              -- predict / retrain / ack_alert
    target          TEXT,                              -- ex. account_id
    details         JSONB,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_ts_idx ON analytics.audit_log (ts DESC);

-- Terminé - dbt + Great Expectations créeront leurs propres artefacts.
