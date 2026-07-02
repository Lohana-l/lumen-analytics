-- assert_mrr_movements_reconcile
-- ------------------------------------------------------------------
-- Pour chaque mois, la somme des delta_mrr sur tous les types de mouvement
-- doit égaler total_current_mrr - total_prior_mrr. Si ce n'est pas le cas,
-- le waterfall est cassé - la sortie du test dbt le signale.
-- ------------------------------------------------------------------
with roll_up as (
    select
        month_start,
        sum(delta_mrr) as delta_total,
        sum(mrr)       as mrr_total,
        sum(prev_mrr)  as prev_mrr_total
    from {{ ref('fct_mrr_movements') }}
    group by 1
),
mismatches as (
    select *
    from roll_up
    where abs(delta_total - (mrr_total - prev_mrr_total)) > 0.01
)
select * from mismatches
