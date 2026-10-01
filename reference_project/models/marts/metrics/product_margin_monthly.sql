with

orders as (

    select * from {{ ref('orders') }}

),

order_items as (

    select * from {{ ref('order_items') }}

),

customers as (

    select * from {{ ref('stg_customers') }}

),

refunds as (

    select * from {{ ref('stg_refunds') }}

),

products as (

    select * from {{ ref('stg_products') }}

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

qualifying_items as (

    select
        order_items.order_item_id,
        order_items.product_id,
        order_items.product_price,
        order_items.supply_cost,
        qualifying_orders.ordered_at_ts

    from order_items

    inner join qualifying_orders
        on order_items.order_id = qualifying_orders.order_id

),

monthly as (

    select
        date_trunc('month', qualifying_items.ordered_at_ts) as order_month,
        qualifying_items.product_id,

        count(qualifying_items.order_item_id) as units_sold,
        sum(qualifying_items.product_price) as revenue,
        sum(qualifying_items.supply_cost) as supply_cost

    from qualifying_items

    group by 1, 2

)

select
    cast(monthly.order_month as date) as order_month,
    monthly.product_id,
    products.product_name,
    cast(monthly.units_sold as bigint) as units_sold,
    cast(monthly.revenue as decimal(18, 2)) as revenue,
    cast(monthly.supply_cost as decimal(18, 2)) as supply_cost,
    cast(monthly.revenue - monthly.supply_cost as decimal(18, 2)) as gross_margin

from monthly

inner join products
    on monthly.product_id = products.product_id
