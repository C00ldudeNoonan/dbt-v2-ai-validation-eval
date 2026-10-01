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

),

first_orders as (

    select
        customer_id,
        min(ordered_at_ts) as first_ordered_at

    from qualifying_orders

    group by 1

),

classified_orders as (

    select
        date_trunc('month', qualifying_orders.ordered_at_ts) as order_month,
        case
            when date_trunc('month', qualifying_orders.ordered_at_ts)
                = date_trunc('month', first_orders.first_ordered_at)
                then 'new'
            else 'returning'
        end as customer_type,
        qualifying_orders.customer_id,
        qualifying_orders.order_id,
        qualifying_orders.order_total

    from qualifying_orders

    inner join first_orders
        on qualifying_orders.customer_id = first_orders.customer_id

)

select
    cast(order_month as date) as order_month,
    customer_type,
    cast(count(distinct customer_id) as bigint) as customers,
    cast(count(order_id) as bigint) as order_count,
    cast(sum(order_total) as decimal(18, 2)) as revenue_gross

from classified_orders

group by 1, 2
