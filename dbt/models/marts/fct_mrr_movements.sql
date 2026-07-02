-- fct_mrr_movements
-- ------------------------------------------------------------------
-- Calcule les composantes du waterfall MRR mois après mois :
--   new / expansion / contraction / churn / steady
-- Vérifié par tests/assert_mrr_movements_reconcile.sql
--
-- Limitation assumée : pas de type "reactivation". Un compte qui revient
-- après un churn (prev_mrr = 0, mrr > 0) est classé "new". Distinguer les
-- deux demanderait un scan de tout l'historique du compte, sans bénéfice
-- pour les KPIs servis (NRR/GRR agrègent new + expansion identiquement).
--
-- Garde-fou : on borne le résultat au dernier mois réellement présent
-- dans fct_mrr_monthly. Sans ça, le décalage de +1 mois côté prev_month
-- crée un mois fantôme où tous les comptes sont marqués "churn" (mrr=0,
-- prev_mrr=valeur réelle), ce qui fausse le waterfall du dernier mois.
-- ------------------------------------------------------------------
{{ config(materialized='table') }}

with this_month as (
    select month_start, account_id, mrr
    from {{ ref('fct_mrr_monthly') }}
),
prev_month as (
    select
        (month_start + interval '1 month')::date as month_start,
        account_id,
        mrr                                     as prev_mrr
    from {{ ref('fct_mrr_monthly') }}
),
max_observed as (
    select max(month_start) as max_month
    from {{ ref('fct_mrr_monthly') }}
),
joined as (
    select
        coalesce(t.month_start, p.month_start) as month_start,
        coalesce(t.account_id,  p.account_id)  as account_id,
        coalesce(t.mrr, 0)                     as mrr,
        coalesce(p.prev_mrr, 0)                as prev_mrr
    from this_month t
    full outer join prev_month p
      on  t.month_start = p.month_start
     and  t.account_id  = p.account_id
)
select
    j.month_start,
    j.account_id,
    j.mrr,
    j.prev_mrr,
    case
        when j.prev_mrr = 0 and j.mrr > 0          then 'new'
        when j.prev_mrr > 0 and j.mrr = 0          then 'churn'
        when j.prev_mrr > 0 and j.mrr > j.prev_mrr then 'expansion'
        when j.prev_mrr > 0 and j.mrr < j.prev_mrr then 'contraction'
        else 'steady'
    end                                        as movement_type,
    (j.mrr - j.prev_mrr)                       as delta_mrr
from joined j
cross join max_observed m
where j.month_start <= m.max_month
