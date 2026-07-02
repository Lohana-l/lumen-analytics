-- fct_mrr_monthly
-- ------------------------------------------------------------------
-- Pour chaque mois × compte, le MRR actif au 1er du mois.
-- Sert de base à l'analyse des mouvements MRR.
-- ------------------------------------------------------------------
{{ config(materialized='table') }}

with month_starts as (
    select distinct date_trunc('month', date_day)::date as month_start
    from {{ ref('dim_date') }}
    where date_day <= '{{ var("reporting_date") }}'::date
),
subs as (
    select * from {{ ref('int_subscription_history') }}
)
select
    ms.month_start,
    s.account_id,
    s.plan,
    s.seats,
    s.mrr,
    to_char(ms.month_start, 'YYYY-MM') as year_month
from month_starts ms
join subs s
  on ms.month_start >= s.valid_from::date
 and ms.month_start <  s.valid_to_eff::date
