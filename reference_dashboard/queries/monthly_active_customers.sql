-- Reference dashboard: monthly active customers. Reads raw tables only.
with real_orders as (
    select o.*
    from raw.raw_orders o
    join raw.raw_customers c on c.id = o.customer
    where c.name not like 'QA Test Account%'
      and not exists (select 1 from raw.raw_refunds r where r.order_id = o.id)
)
select
    cast(date_trunc('month', ordered_at) as date) as activity_month,
    count(distinct customer) as active_customers,
    count(*) as order_count,
    count(*) * 1.0 / count(distinct customer) as orders_per_active_customer
from real_orders
group by 1
