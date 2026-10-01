-- Reference dashboard: monthly revenue by store. Reads raw tables only.
with real_orders as (
    select o.*
    from raw.raw_orders o
    join raw.raw_customers c on c.id = o.customer
    where c.name not like 'QA Test Account%'
      and not exists (select 1 from raw.raw_refunds r where r.order_id = o.id)
)
select
    cast(date_trunc('month', o.ordered_at) as date) as order_month,
    o.store_id as location_id,
    s.name as location_name,
    count(*) as order_count,
    sum(o.subtotal) / 100.0 as revenue_pretax,
    sum(o.order_total) / 100.0 as revenue_gross
from real_orders o
join raw.raw_stores s on s.id = o.store_id
group by 1, 2, 3
