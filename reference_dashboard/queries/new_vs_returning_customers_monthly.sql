-- Reference dashboard: new vs returning customers by month. Reads raw tables only.
with real_orders as (
    select o.*, date_trunc('month', o.ordered_at) as m
    from raw.raw_orders o
    join raw.raw_customers c on c.id = o.customer
    where c.name not like 'QA Test Account%'
      and not exists (select 1 from raw.raw_refunds r where r.order_id = o.id)
),
cohorts as (
    select customer, min(m) as cohort_month
    from real_orders
    group by 1
)
select
    cast(o.m as date) as order_month,
    case when o.m = k.cohort_month then 'new' else 'returning' end as customer_type,
    count(distinct o.customer) as customers,
    count(*) as order_count,
    sum(o.order_total) / 100.0 as revenue_gross
from real_orders o
join cohorts k on k.customer = o.customer
group by 1, 2
