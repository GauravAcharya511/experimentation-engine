-- Gold: the analysis-ready mart. One row per user, carrying everything the
-- statistics layer needs:
--   variant        -> group comparison
--   pre_revenue    -> CUPED covariate (correlated with post-period revenue)
--   tenure/device/country -> heterogeneous treatment effect segments
--   exposure_day   -> sequential / peeking analysis
--   converted, revenue, avg_latency_ms -> primary, secondary, guardrail metrics
select
    a.user_id,
    a.variant,
    a.exposure_day,
    a.tenure,
    a.device,
    a.country,
    a.pre_revenue,
    a.pre_sessions,
    coalesce(m.sessions, 0)   as sessions,
    coalesce(m.revenue, 0.0)  as revenue,
    coalesce(m.converted, 0)  as converted,
    m.avg_latency_ms
from {{ ref('stg_assignments') }} a
left join {{ ref('int_user_session_metrics') }} m
    on a.user_id = m.user_id
