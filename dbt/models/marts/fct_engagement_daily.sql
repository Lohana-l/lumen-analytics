-- fct_engagement_daily : DAU et événements par compte × jour
{{ config(materialized='table') }}

select
    e.event_date,
    e.account_id,
    count(*)                        as events,
    count(distinct e.user_id)       as dau
from {{ ref('stg_events') }} e
group by 1, 2
