-- Silver: aggregate the session log up to one row per user.
-- This is the "raw events -> per-user outcomes" step a real experiment
-- pipeline performs before any statistics run.
select
    user_id,
    count(*)                 as sessions,
    sum(session_revenue)     as revenue,
    max(is_conversion)       as converted,
    avg(latency_ms)          as avg_latency_ms
from {{ ref('stg_events') }}
group by user_id
