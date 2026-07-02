-- fct_tickets_monthly : volume support + CSAT moyen par compte × mois
{{ config(materialized='table') }}

select
    date_trunc('month', opened_ts)::date as month_start,
    account_id,
    count(*)                                 as tickets_opened,
    count(*) filter (where priority = 'urgent') as urgent_tickets,
    avg(csat)                                as avg_csat,
    -- nombre de tickets notés : sert de poids pour réagréger avg_csat en aval
    -- (mart_account_health) sans biais de moyenne de moyennes
    count(csat)                              as rated_tickets,
    avg(hours_to_close)                      as avg_resolution_hours
from {{ ref('stg_tickets') }}
group by 1, 2
