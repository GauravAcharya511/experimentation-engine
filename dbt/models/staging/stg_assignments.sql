-- Silver: typed, renamed, one row per user. No business logic here.
select
    user_id,
    variant,
    exposure_day,
    tenure,
    device,
    country,
    cast(pre_revenue as double)  as pre_revenue,
    cast(pre_sessions as integer) as pre_sessions
from {{ source('raw', 'assignments') }}
