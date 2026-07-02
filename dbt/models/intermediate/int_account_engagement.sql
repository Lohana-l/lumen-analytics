-- int_account_engagement
-- ------------------------------------------------------------------
-- Indicateurs d'engagement par compte sur les 30 derniers jours
-- avant reporting_date. Réutilisé par mart_account_health et les features ML.
-- ------------------------------------------------------------------
{{ config(materialized='ephemeral') }}

with bounds as (
    select
        '{{ var("reporting_date") }}'::date              as report_date,
        '{{ var("reporting_date") }}'::date - 30         as window_start
),
events as (
    select
        e.account_id,
        count(*)                                         as events_30d,
        count(distinct e.user_id)                        as dau_30d_distinct,
        count(distinct e.event_date)                     as active_days_30d,
        max(e.event_ts)                                  as last_event_ts
    from {{ ref('stg_events') }} e
    cross join bounds b
    -- Fenêtre bornée des deux côtés : la borne haute protège du label leakage
    -- même si un événement futur passait (ne pas dépendre uniquement du test
    -- assert_no_future_events pour la correction du calcul).
    where e.event_date >= b.window_start
      and e.event_date <= b.report_date
    group by 1
)
select
    a.account_id,
    coalesce(events.events_30d,        0)                as events_30d,
    coalesce(events.dau_30d_distinct,  0)                as dau_30d_distinct,
    coalesce(events.active_days_30d,   0)                as active_days_30d,
    events.last_event_ts,
    -- proxy DAU/MAU : active_days_30d / 30 (fenêtre de reporting)
    coalesce(events.active_days_30d, 0)::numeric / 30.0  as stickiness_30d
from {{ ref('stg_accounts') }} a
left join events on events.account_id = a.account_id
