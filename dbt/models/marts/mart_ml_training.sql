-- mart_ml_training
-- ------------------------------------------------------------------
-- Jeu d'entraînement POINT-IN-TIME avec COUPURE TEMPORELLE pour le
-- modèle de churn.
--
-- Design (deux problèmes successivement corrigés) :
--
-- 1. Target leakage : photographier les churners à reporting_date les
--    montre POST-churn (mrr=0, activité=0), donc le modèle apprend la
--    conséquence du churn, pas ses précurseurs.
--
-- 2. Mémorisation train/serve : si les comptes actifs sont photographiés
--    à reporting_date pour l'entraînement (négatifs) PUIS scorés à
--    reporting_date en serving, le modèle revoit exactement ses lignes
--    d'entraînement et leur restitue le label mémorisé (~0%), donc tous les
--    scores du dashboard étaient quasi nuls et uniformes.
--
-- Correctif : coupure temporelle unique
--     cut = reporting_date - 180 jours      (= ml.features.CHURN_HORIZON_DAYS)
--
--   - population : comptes ACTIFS à cut (inscrits avant cut, pas encore churnés)
--   - features   : calculées À cut (fenêtres 30j / 90j AVANT cut)
--   - label      : is_churned = a churné dans (cut, reporting_date]
--
-- Les lignes servies (features à reporting_date, via mart_account_health)
-- ne sont ainsi JAMAIS des lignes d'entraînement, et les features des
-- futurs churners sont pré-churn par construction.
--
-- Consommé par ml.train (entraînement) et monitoring.evidently_jobs
-- (distribution de référence du drift). Le serving (ml.predict) reste sur
-- mart_account_health : on score l'état COURANT des comptes actifs.
-- ------------------------------------------------------------------
{{ config(materialized='table') }}

with cutoff as (
    select
        ('{{ var("reporting_date") }}'::date - interval '180 days')::date as cut,
        '{{ var("reporting_date") }}'::date                               as report_date
),

-- Population : comptes actifs à la coupure
base as (
    select
        a.account_id,
        a.company_name,
        a.industry,
        a.country,
        a.acquisition_channel,
        a.signup_ts,
        c.cut                                            as as_of_date,
        -- label : churn dans la fenêtre (cut, reporting_date]
        (a.churned_ts is not null
         and a.churned_ts::date >  c.cut
         and a.churned_ts::date <= c.report_date)        as is_churned
    from {{ ref('stg_accounts') }} a
    cross join cutoff c
    where a.signup_ts::date <= c.cut                          -- inscrit avant la coupure
      and (a.churned_ts is null or a.churned_ts::date > c.cut) -- encore actif à la coupure
),

-- Abonnement en vigueur à la coupure : MRR, plan et sièges pré-churn
sub_at as (
    select
        b.account_id,
        s.plan,
        s.seats,
        s.mrr
    from base b
    join {{ ref('int_subscription_history') }} s
      on  s.account_id = b.account_id
      and s.valid_from   <= b.as_of_date::timestamptz
      and s.valid_to_eff >  b.as_of_date::timestamptz
),

-- Engagement produit : fenêtre (cut - 30j, cut]
ev as (
    select
        b.account_id,
        count(*)                      as events_30d,
        count(distinct e.user_id)     as dau_30d_distinct,
        count(distinct e.event_date)  as active_days_30d
    from base b
    join {{ ref('stg_events') }} e
      on  e.account_id = b.account_id
      and e.event_date >  b.as_of_date - 30
      and e.event_date <= b.as_of_date
    group by 1
),

-- Facturation : fenêtre (cut - 90j, cut]
inv as (
    select
        b.account_id,
        count(*) filter (where i.status = 'paid')    as invoices_paid_count,
        count(*) filter (where i.status = 'overdue') as invoices_overdue_count,
        count(*) filter (where i.status = 'failed')  as invoices_failed_count
    from base b
    join {{ ref('stg_invoices') }} i
      on  i.account_id = b.account_id
      and i.issued_ts >= (b.as_of_date - 90)::timestamptz
      and i.issued_ts <  (b.as_of_date + 1)::timestamptz
    group by 1
),

-- Support : fenêtre (cut - 90j, cut]
tk as (
    select
        b.account_id,
        count(*)                                       as tickets_90d,
        count(*) filter (where t.priority = 'urgent')  as urgent_tickets_90d
    from base b
    join {{ ref('stg_tickets') }} t
      on  t.account_id = b.account_id
      and t.opened_ts >= (b.as_of_date - 90)::timestamptz
      and t.opened_ts <  (b.as_of_date + 1)::timestamptz
    group by 1
)

select
    b.account_id,
    b.industry,
    b.country,
    b.acquisition_channel,
    b.is_churned,
    b.as_of_date,
    -- attributs au moment de la coupure (pas la valeur courante du compte)
    coalesce(s.plan,  'starter')                       as current_plan,
    coalesce(s.seats, 1)                               as current_seats,
    coalesce(s.mrr,   0)                               as mrr,
    -- ancienneté À LA COUPURE : même convention que dim_account
    extract(epoch from (b.as_of_date::timestamptz - b.signup_ts))
        / (86400.0 * 30)                               as tenure_months,
    extract(epoch from (b.as_of_date::timestamptz - b.signup_ts))
        / 86400.0                                      as days_since_signup,
    coalesce(ev.events_30d,       0)                   as events_30d,
    coalesce(ev.dau_30d_distinct, 0)                   as dau_30d_distinct,
    coalesce(ev.active_days_30d,  0)                   as active_days_30d,
    coalesce(ev.active_days_30d,  0)::numeric / 30.0   as stickiness_30d,
    coalesce(inv.invoices_paid_count,    0)            as invoices_paid_count,
    coalesce(inv.invoices_overdue_count, 0)            as invoices_overdue_count,
    coalesce(inv.invoices_failed_count,  0)            as invoices_failed_count,
    coalesce(tk.tickets_90d,        0)                 as tickets_90d,
    coalesce(tk.urgent_tickets_90d, 0)                 as urgent_tickets_90d
from base b
left join sub_at s  on s.account_id  = b.account_id
left join ev        on ev.account_id = b.account_id
left join inv       on inv.account_id = b.account_id
left join tk        on tk.account_id  = b.account_id
