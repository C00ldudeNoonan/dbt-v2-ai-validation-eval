with

source as (

    select * from {{ source('ecom', 'raw_refunds') }}

),

renamed as (

    select

        ----------  ids
        order_id,

        ---------- text
        reason as refund_reason,

        ---------- timestamps
        refunded_at

    from source

)

select * from renamed
