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

locations as (

    select * from {{ ref('stg_locations') }}

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

monthly as (

    select
        date_trunc('month', qualifying_orders.ordered_at_ts) as order_month,
        qualifying_orders.location_id,

        count(qualifying_orders.order_id) as order_count,
        sum(qualifying_orders.subtotal) as revenue_pretax,
        sum(qualifying_orders.order_total) as revenue_gross

    from qualifying_orders

    group by 1, 2

)

select
    cast(monthly.order_month as date) as order_month,
    monthly.location_id,
    locations.location_name,
    cast(monthly.order_count as bigint) as order_count,
    cast(monthly.revenue_pretax as decimal(18, 2)) as revenue_pretax,
    cast(monthly.revenue_gross as decimal(18, 2)) as revenue_gross

from monthly

inner join locations
    on monthly.location_id = locations.location_id
