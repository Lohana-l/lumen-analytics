-- int_billing_history
-- Santé de facturation agrégée par compte sur les 90 derniers jours.
{{ config(materialized='ephemeral') }}

with bounds as (
    select
        '{{ var("reporting_date") }}'::date              as report_date,
        '{{ var("reporting_date") }}'::date - 90         as window_start
),
inv as (
    select
        i.account_id,
        count(*) filter (where i.status = 'paid')                       as invoices_paid_count,
        count(*) filter (where i.status = 'overdue')                    as invoices_overdue_count,
        count(*) filter (where i.status = 'failed')                     as invoices_failed_count,
        avg(i.days_to_pay)                                              as avg_days_to_pay
    from {{ ref('stg_invoices') }} i
    cross join bounds b
    -- Fenêtre bornée des deux côtés, comme int_account_engagement.
    where i.issued_ts >= b.window_start
      and i.issued_ts <  b.report_date + 1
    group by 1
)
select
    a.account_id,
    coalesce(inv.invoices_paid_count,    0)  as invoices_paid_count,
    coalesce(inv.invoices_overdue_count, 0)  as invoices_overdue_count,
    coalesce(inv.invoices_failed_count,  0)  as invoices_failed_count,
    inv.avg_days_to_pay
from {{ ref('stg_accounts') }} a
left join inv on inv.account_id = a.account_id
