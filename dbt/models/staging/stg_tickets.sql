{{ config(materialized='view') }}

select
    ticket_id,
    account_id,
    category,
    opened_ts::timestamptz                    as opened_ts,
    closed_ts::timestamptz                    as closed_ts,
    priority,
    csat,
    case
        when closed_ts is not null
             then extract(epoch from closed_ts - opened_ts) / 3600.0
    end                                       as hours_to_close
from {{ source('raw', 'tickets') }}
