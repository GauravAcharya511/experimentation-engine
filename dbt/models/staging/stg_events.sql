-- Silver: session-grain event log, lightly typed.
select
    user_id,
    cast(event_day as integer)      as event_day,
    cast(session_revenue as double) as session_revenue,
    cast(latency_ms as double)      as latency_ms,
    cast(is_conversion as integer)  as is_conversion
from {{ source('raw', 'events') }}
