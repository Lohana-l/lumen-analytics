-- Par compte, les abonnements successifs ne doivent pas se chevaucher dans le temps.
with pairs as (
    select
        account_id,
        subscription_id,
        valid_from,
        valid_to,
        lead(valid_from) over (partition by account_id order by valid_from) as next_from
    from {{ ref('stg_subscriptions') }}
)
select *
from pairs
where valid_to is not null
  and next_from is not null
  and valid_to > next_from
