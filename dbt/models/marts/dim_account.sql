-- dim_account : une ligne par client, tous les attributs à évolution lente
-- ramenés à leur valeur *courante*, avec tenure_months comme champ dérivé.
{{ config(materialized='table') }}

select
    a.account_id,
    a.company_name,
    a.industry,
    a.country,
    a.current_plan,
    a.current_seats,
    a.acquisition_channel,
    a.signup_ts,
    a.churned_ts,
    a.is_churned,
    extract(
        epoch from (
            coalesce(a.churned_ts, '{{ var("reporting_date") }}'::timestamptz)
            - a.signup_ts
        )
    ) / (86400.0 * 30) as tenure_months,
    extract(
        epoch from (
            '{{ var("reporting_date") }}'::timestamptz - a.signup_ts
        )
    ) / 86400.0          as days_since_signup
from {{ ref('stg_accounts') }} a
