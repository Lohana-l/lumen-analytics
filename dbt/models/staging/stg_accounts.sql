-- stg_accounts : une ligne propre par client, colonnes typées.
{{ config(materialized='view') }}

select
    account_id,
    company_name,
    industry,
    country,
    plan                                      as current_plan,
    seats                                     as current_seats,
    signup_ts::timestamptz                    as signup_ts,
    churned_ts::timestamptz                   as churned_ts,
    (churned_ts is not null)                  as is_churned,
    acquisition_ch                            as acquisition_channel,
    created_at::timestamptz                   as ingested_at
from {{ source('raw', 'accounts') }}
