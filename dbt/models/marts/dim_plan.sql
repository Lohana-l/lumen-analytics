{{ config(materialized='table') }}

select * from (values
    ('starter',    49,  'Starter'),
    ('pro',        149, 'Pro'),
    ('enterprise', 499, 'Enterprise')
) as t(plan_id, list_price_per_seat, plan_label)
