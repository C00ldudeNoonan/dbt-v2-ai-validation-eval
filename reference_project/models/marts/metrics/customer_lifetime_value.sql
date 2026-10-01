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

    select
        orders.*,
        customers.customer_name

    from orders

    inner join customers
        on orders.customer_id = customers.customer_id

    left join refunds
        on orders.order_id = refunds.order_id

    where not customers.is_test_account
        and refunds.order_id is null

)

select
    qualifying_orders.customer_id,
    qualifying_orders.customer_name,
    cast(min(qualifying_orders.ordered_at_ts) as date) as first_order_date,
    cast(max(qualifying_orders.ordered_at_ts) as date) as last_order_date,
    cast(count(qualifying_orders.order_id) as bigint) as lifetime_orders,
    cast(sum(qualifying_orders.order_total) as decimal(18, 2)) as lifetime_revenue,
    cast(sum(qualifying_orders.order_total) as double)
        / count(qualifying_orders.order_id) as avg_order_value,
    cast(avg(qualifying_orders.order_cost) as double) as avg_order_supply_cost

from qualifying_orders

group by 1, 2
