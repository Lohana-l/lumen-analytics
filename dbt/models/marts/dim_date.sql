-- dim_date : spine de dates sur 3 ans couvrant les données seedées.
{{ config(materialized='table') }}

with bounds as (
    select
        '2024-01-01'::date as min_d,
        '2027-01-01'::date as max_d
),
spine as (
    select generate_series(min_d, max_d, '1 day'::interval)::date as date_day
    from bounds
)
select
    date_day,
    extract(year   from date_day)::int as year,
    extract(month  from date_day)::int as month,
    extract(day    from date_day)::int as day,
    extract(dow    from date_day)::int as day_of_week,
    extract(quarter from date_day)::int as quarter,
    to_char(date_day, 'YYYY-MM')       as year_month
from spine
