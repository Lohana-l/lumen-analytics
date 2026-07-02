{{ config(materialized='table') }}

select distinct industry as industry_id, industry as industry_label
from {{ ref('stg_accounts') }}
