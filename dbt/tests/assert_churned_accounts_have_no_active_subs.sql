-- Un compte dont churned_ts est renseigné ne doit plus avoir d'abonnement
-- actif (valid_to IS NULL) après ce timestamp.
select
    a.account_id,
    a.churned_ts,
    s.subscription_id
from {{ ref('stg_accounts') }} a
join {{ ref('stg_subscriptions') }} s using (account_id)
where a.churned_ts is not null
  and s.valid_to is null
