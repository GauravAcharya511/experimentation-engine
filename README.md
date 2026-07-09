# Experimentation Analysis Engine

An end-to-end A/B test analysis engine that takes a raw event stream, models it
into experiment-ready metrics, and produces a rigorous ship / no-ship readout —
power, variance-reduced treatment effects (CUPED), sequential-testing
corrections, multiple-comparison control, and heterogeneous (segment-level)
effects.

## Why this is built on simulated data (on purpose)

An experimentation platform is only trustworthy if its estimators are correctly
calibrated. You cannot verify calibration on real data, because the true effect
is unknown. This project therefore generates data with **injected ground-truth
effects** (`data/ground_truth.json`) and grades every estimator against them:
the treatment effect must be recovered within its confidence interval, the
false-positive rate must match alpha, and observed power must match the design.
Controlled simulation is how real experimentation teams test their own systems.

## Stack

Python (pandas, scipy, statsmodels) · DuckDB (local warehouse) · dbt
(event-to-metric modeling) · Streamlit (readout) · GitHub Actions (CI). The dbt
profile is DuckDB by default and swappable to BigQuery.

## Quickstart

```bash
make setup          # venv + dependencies
make data           # generate the dataset (writes data/*.parquet + ground_truth.json)
```

Or without make:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python src/simulate.py
```

## Data model

`src/simulate.py` emits two raw tables (the grain a real pipeline ingests):

- `assignments.parquet` — one row per user: variant, exposure day, pre-period
  covariates (`pre_revenue`, `pre_sessions`), and segments (tenure/device/country).
- `events.parquet` — one row per session: `session_revenue`, `latency_ms`,
  `is_conversion`. dbt re-aggregates these to per-user metrics.

The generator injects a small primary-metric lift, a continuous revenue lift
correlated with the pre-period (so CUPED has leverage), a **null** guardrail
(latency), and **heterogeneous** effects by tenure (new users respond more).

## Roadmap

- [x] Phase 1 — reproducible data generator with ground-truth validation harness
- [ ] Phase 2 — dbt models: raw events → per-user experiment metric marts
- [ ] Phase 3 — analysis engine: power, t-test/proportions, CUPED, sequential,
      multiple-comparison correction, heterogeneous treatment effects (+ tests)
- [ ] Phase 4 — Streamlit experiment-readout dashboard
- [ ] Phase 5 — GitHub Actions CI (regenerate data, run dbt, run tests)
