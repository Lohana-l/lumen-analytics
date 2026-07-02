-- int_subscription_history
-- ------------------------------------------------------------------
-- Ferme le bord droit de valid_to avec le valid_from de l'abonnement
-- suivant pour permettre des jointures point-in-time sur le MRR.
--
-- L'abonnement EN COURS (valid_to null, pas de suivant) est fermé par une
-- sentinelle futur lointain, PAS par reporting_date : les jointures aval
-- testent `date < valid_to_eff` (borne exclusive), donc fermer à
-- reporting_date excluait l'abonnement actif de tous les comptes au moment
-- du reporting (mrr = 0 partout dans mart_account_health).
-- ------------------------------------------------------------------
{{ config(materialized='ephemeral') }}

with ranked as (
    select
        subscription_id,
        account_id,
        plan,
        seats,
        mrr,
        valid_from,
        valid_to,
        lead(valid_from) over (
            partition by account_id order by valid_from
        ) as next_valid_from
    from {{ ref('stg_subscriptions') }}
)
select
    subscription_id,
    account_id,
    plan,
    seats,
    mrr,
    valid_from,
    coalesce(valid_to, next_valid_from, '9999-12-31'::timestamptz) as valid_to_eff
from ranked
