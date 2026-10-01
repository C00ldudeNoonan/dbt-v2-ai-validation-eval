-- Reference dashboard: daily order activity. Reads raw tables only.
with real_orders as (
    select o.*
    from raw.raw_orders o
    join raw.raw_customers c on c.id = o.customer
    where c.name not like 'QA Test Account%'
      and not exists (select 1 from raw.raw_refunds r where r.order_id = o.id)
),
item_counts as (
    select order_id, count(*) as n_items
    from raw.raw_items
    group by 1
)
select
    cast(o.ordered_at as date) as order_date,
    count(*) as order_count,
    count(distinct o.customer) as customer_count,
    sum(i.n_items) as item_count,
    avg(i.n_items) as avg_items_per_order,
    sum(o.order_total) / 100.0 as revenue_gross
from real_orders o
left join item_counts i on i.order_id = o.id
group by 1
