{{ config(materialized='view') }}

select
    subscription_id,
    account_id,
    plan,
    seats,
    mrr,
    valid_from::timestamptz                   as valid_from,
    valid_to::timestamptz                     as valid_to,
    (valid_to is null)                        as is_active
from {{ source('raw', 'subscriptions') }}
