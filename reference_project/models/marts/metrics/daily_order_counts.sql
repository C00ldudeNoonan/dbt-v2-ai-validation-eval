with

orders as (

    select * from {{ ref('orders') }}

),

customers as (

    select * from {{ ref('stg_customers') }}

),

refunds as (

    select * from {{ ref('stg_refunds') }}

),

qualifying_orders as (

    select orders.*

    from orders

    inner join customers
        on orders.customer_id = customers.customer_id

    left join refunds
        on orders.order_id = refunds.order_id

    where not customers.is_test_account
        and refunds.order_id is null

)

select
    cast(date_trunc('day', qualifying_orders.ordered_at_ts) as date) as order_date,
    cast(count(qualifying_orders.order_id) as bigint) as order_count,
    cast(count(distinct qualifying_orders.customer_id) as bigint) as customer_count,
    cast(sum(qualifying_orders.count_order_items) as bigint) as item_count,
    cast(avg(qualifying_orders.count_order_items) as double) as avg_items_per_order,
    cast(sum(qualifying_orders.order_total) as decimal(18, 2)) as revenue_gross

from qualifying_orders

group by 1
