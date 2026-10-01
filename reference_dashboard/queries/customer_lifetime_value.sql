-- Reference dashboard: customer lifetime value. Reads raw tables only.
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
),
order_costs as (
    select i.order_id, sum(s.cost_cents) / 100.0 as order_cost
    from raw.raw_items i
    join supply_cost_per_sku s on s.sku = i.sku
    group by 1
)
select
    o.customer as customer_id,
    c.name as customer_name,
    cast(min(o.ordered_at) as date) as first_order_date,
    cast(max(o.ordered_at) as date) as last_order_date,
    count(*) as lifetime_orders,
    sum(o.order_total) / 100.0 as lifetime_revenue,
    sum(o.order_total) / 100.0 / count(*) as avg_order_value,
    avg(oc.order_cost) as avg_order_supply_cost
from real_orders o
join raw.raw_customers c on c.id = o.customer
left join order_costs oc on oc.order_id = o.id
group by 1, 2
