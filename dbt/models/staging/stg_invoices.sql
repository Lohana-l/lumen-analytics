{{ config(materialized='view') }}

select
    invoice_id,
    account_id,
    amount,
    issued_ts::timestamptz                    as issued_ts,
    paid_ts::timestamptz                      as paid_ts,
    status,
    case
        when status = 'paid' and paid_ts is not null
             then extract(epoch from paid_ts - issued_ts) / 86400.0
    end                                       as days_to_pay
from {{ source('raw', 'invoices') }}
