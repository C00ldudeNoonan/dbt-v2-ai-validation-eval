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
    cast(date_trunc('month', qualifying_orders.ordered_at_ts) as date) as activity_month,
    cast(count(distinct qualifying_orders.customer_id) as bigint) as active_customers,
    cast(count(qualifying_orders.order_id) as bigint) as order_count,
    cast(count(qualifying_orders.order_id) as double)
        / count(distinct qualifying_orders.customer_id) as orders_per_active_customer

from qualifying_orders

group by 1
