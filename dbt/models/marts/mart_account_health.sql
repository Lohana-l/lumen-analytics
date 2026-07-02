-- mart_account_health
-- ------------------------------------------------------------------
-- Une ligne par compte à reporting_date, croisant engagement + facturation
-- + MRR en cours. Consommé par Streamlit, Evidently et les features ML.
-- ------------------------------------------------------------------
{{ config(materialized='table') }}

with current_mrr as (
    select account_id, mrr
    from {{ ref('int_subscription_history') }}
    where '{{ var("reporting_date") }}'::timestamptz >= valid_from
      and '{{ var("reporting_date") }}'::timestamptz <  valid_to_eff
),
ticket_90 as (
    select
        account_id,
        sum(tickets_opened)  as tickets_90d,
        sum(urgent_tickets)  as urgent_tickets_90d,
        -- moyenne pondérée par le nombre de tickets notés : avg(avg_csat)
        -- donnerait le même poids à un mois avec 1 ticket qu'à un mois avec 12
        sum(avg_csat * rated_tickets) / nullif(sum(rated_tickets), 0)
                             as avg_csat_90d
    from {{ ref('fct_tickets_monthly') }}
    where month_start >= '{{ var("reporting_date") }}'::date - 90
    group by 1
)
select
    a.account_id,
    a.company_name,
    a.industry,
    a.country,
    a.current_plan,
    a.current_seats,
    a.tenure_months,
    a.days_since_signup,
    a.acquisition_channel,
    a.is_churned,
    coalesce(c.mrr, 0)                               as mrr,
    e.events_30d,
    e.dau_30d_distinct,
    e.active_days_30d,
    e.stickiness_30d,
    e.last_event_ts,
    b.invoices_paid_count,
    b.invoices_overdue_count,
    b.invoices_failed_count,
    coalesce(t.tickets_90d,        0)                as tickets_90d,
    coalesce(t.urgent_tickets_90d, 0)                as urgent_tickets_90d,
    t.avg_csat_90d,
    -- Score de santé rule-based simple (0-100). Le vrai scoring, c'est le modèle ML.
    greatest(0, least(100,
        50
        + 20 * (e.stickiness_30d - 0.2)      -- usage produit
        -  5 * coalesce(b.invoices_overdue_count, 0)
        -  8 * coalesce(b.invoices_failed_count,  0)
        -  3 * coalesce(t.urgent_tickets_90d, 0)
    ))::numeric(5, 2)                                as rule_based_health_score
from {{ ref('dim_account') }} a
left join current_mrr                c on c.account_id = a.account_id
left join {{ ref('int_account_engagement') }} e on e.account_id = a.account_id
left join {{ ref('int_billing_history')    }} b on b.account_id = a.account_id
left join ticket_90                  t on t.account_id = a.account_id
