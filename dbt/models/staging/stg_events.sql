{{ config(materialized='view') }}

select
    event_id,
    account_id,
    user_id,
    event_type,
    event_ts::timestamptz                     as event_ts,
    date_trunc('day', event_ts)::date         as event_date
from {{ source('raw', 'events') }}
