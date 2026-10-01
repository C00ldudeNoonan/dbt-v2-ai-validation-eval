-- Reference dashboard: monthly product margin. Reads raw tables only.
with real_orders as (
    select o.*
    from raw.raw_orders o
    join raw.raw_customers c on c.id = o.customer
    where c.name not like 'QA Test Account%'
      and not exists (select 1 from raw.raw_refunds r where r.order_id = o.id)
),
supply_cost_per_sku as (
    select sku, sum(cost) as cost_cents
    from raw.raw_supplies
    group by 1
)
select
    cast(date_trunc('month', o.ordered_at) as date) as order_month,
    i.sku as product_id,
    p.name as product_name,
    count(*) as units_sold,
    sum(p.price) / 100.0 as revenue,
    sum(s.cost_cents) / 100.0 as supply_cost,
    (sum(p.price) - sum(s.cost_cents)) / 100.0 as gross_margin
from raw.raw_items i
join real_orders o on o.id = i.order_id
join raw.raw_products p on p.sku = i.sku
left join supply_cost_per_sku s on s.sku = i.sku
group by 1, 2, 3
