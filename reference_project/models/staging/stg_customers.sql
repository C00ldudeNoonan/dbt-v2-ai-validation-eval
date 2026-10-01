with

source as (

    select * from {{ source('ecom', 'raw_customers') }}

),

renamed as (

    select

        ----------  ids
        id as customer_id,

        ---------- text
        name as customer_name,

        ---------- booleans
        -- evaluation addition: internal QA accounts are excluded from business metrics
        coalesce(name like 'QA Test Account%', false) as is_test_account

    from source

)

select * from renamed
