"""
Synthetic experiment data generator with KNOWN ground-truth effects.

Why this exists
---------------
An experimentation engine is only trustworthy if its estimators are
correctly calibrated. The only way to *prove* calibration is to run the
estimators against data where the true effect is known, then check that
the estimate recovers it within its confidence interval, that the false
positive rate matches alpha, and that power matches expectation.

This module produces such data. It emits raw, event-level tables that
mirror what a real experimentation pipeline ingests (raw events +
assignment log), and writes the injected ground truth to
`data/ground_truth.json` as the answer key the analysis layer is graded
against.

Covariates are deliberately engineered so each downstream technique has
something to bite on:
  - a pre-experiment metric correlated with the outcome  -> CUPED works
  - segments with different true effects                 -> HTE analysis
  - a per-user exposure day                              -> sequential test
  - multiple metrics incl. a null guardrail              -> multiple testing
  - configurable assignment ratio                        -> SRM detection
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# Experiment configuration (the "design" of the simulated A/B test)
# --------------------------------------------------------------------------- #

@dataclass
class ExperimentConfig:
    seed: int = 42
    n_users: int = 60_000
    experiment_days: int = 14

    # Assignment. treatment_share = 0.5 is a clean 50/50 split.
    # Set e.g. 0.505 to inject a sample-ratio-mismatch the SRM check should catch.
    treatment_share: float = 0.50

    # Population mix
    share_new_users: float = 0.35            # rest are "returning"
    devices: tuple = ("ios", "android", "web")
    device_probs: tuple = (0.40, 0.40, 0.20)
    countries: tuple = ("US", "IN", "BR", "UK", "DE")
    country_probs: tuple = (0.45, 0.20, 0.12, 0.13, 0.10)

    # --- Ground-truth effects (this is the answer key) --- #
    # Primary metric: conversion (binary). Baseline control rate + absolute lift.
    base_conversion: float = 0.120
    conv_lift_new: float = 0.014             # heterogeneous: new users respond more
    conv_lift_returning: float = 0.005

    # Secondary metric: revenue per user (continuous), correlated with pre-period.
    revenue_lift: float = 0.80               # absolute $ lift on a ~$15 mean

    # Guardrail metric: latency (ms). True effect is ZERO (guardrail should pass).
    latency_true_effect_ms: float = 0.0

    # Strength of pre/post correlation. Higher -> CUPED removes more variance.
    pre_post_corr: float = 0.6


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #

def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def generate_users(cfg: ExperimentConfig, rng: np.random.Generator) -> pd.DataFrame:
    n = cfg.n_users
    user_id = np.arange(1, n + 1)

    # Latent user "quality" z ~ N(0,1). This single latent drives BOTH the
    # pre-period metric and the post-period outcome, which is what creates
    # the pre/post correlation CUPED exploits.
    z = rng.standard_normal(n)

    tenure = np.where(rng.random(n) < cfg.share_new_users, "new", "returning")
    device = rng.choice(cfg.devices, size=n, p=cfg.device_probs)
    country = rng.choice(cfg.countries, size=n, p=cfg.country_probs)

    # Returning users are "warmer": shift their latent up a bit.
    z = z + np.where(tenure == "returning", 0.35, 0.0)

    # Pre-experiment revenue (the CUPED covariate). Lognormal-ish, tied to z.
    pre_revenue = np.exp(2.4 + 0.45 * z + 0.25 * rng.standard_normal(n))
    pre_sessions = rng.poisson(lam=np.clip(3 + 1.2 * z, 0.3, None))

    # Randomized assignment.
    variant = np.where(rng.random(n) < cfg.treatment_share, "treatment", "control")

    # Each user is first exposed on some day of the experiment window.
    exposure_day = rng.integers(0, cfg.experiment_days, size=n)

    return pd.DataFrame(
        {
            "user_id": user_id,
            "variant": variant,
            "exposure_day": exposure_day,
            "tenure": tenure,
            "device": device,
            "country": country,
            "pre_revenue": pre_revenue.round(2),
            "pre_sessions": pre_sessions,
            "_z": z,  # latent, dropped before writing
        }
    )


def assign_outcomes(cfg: ExperimentConfig, users: pd.DataFrame,
                    rng: np.random.Generator) -> pd.DataFrame:
    n = len(users)
    z = users["_z"].to_numpy()
    is_treat = (users["variant"] == "treatment").to_numpy()
    is_new = (users["tenure"] == "new").to_numpy()

    # ---- Primary: conversion (binary) ----
    # Baseline propensity varies with latent z (so it's not constant), centered
    # so the control mean lands near cfg.base_conversion.
    base_p = np.clip(cfg.base_conversion + 0.03 * z, 0.01, 0.95)
    lift = np.where(is_new, cfg.conv_lift_new, cfg.conv_lift_returning)
    p_conv = base_p + is_treat * lift
    converted = (rng.random(n) < np.clip(p_conv, 0.0, 1.0)).astype(int)

    # ---- Secondary: revenue per user (continuous, observed for ALL users) ----
    # Correlated with the pre-period via the shared latent z, which is exactly
    # the structure CUPED exploits. This spend is later apportioned across the
    # user's sessions in the event log, so dbt re-derives it by summation.
    pre_std = (z - z.mean()) / z.std()
    noise = rng.standard_normal(n)
    post_signal = (cfg.pre_post_corr * pre_std
                   + np.sqrt(1 - cfg.pre_post_corr**2) * noise)
    user_revenue = 15.0 + 6.0 * post_signal + is_treat * cfg.revenue_lift
    user_revenue = np.clip(user_revenue, 0.0, None)

    # ---- Guardrail: latency (ms), true effect zero ----
    latency = 220 + 40 * rng.standard_normal(n) + is_treat * cfg.latency_true_effect_ms
    latency = np.clip(latency, 30, None)

    out = users.copy()
    out["converted"] = converted
    out["user_revenue"] = user_revenue.round(2)
    out["latency_ms"] = latency.round(1)
    return out


def explode_to_events(users_out: pd.DataFrame, cfg: ExperimentConfig,
                      rng: np.random.Generator) -> pd.DataFrame:
    """Expand per-user outcomes into a session-level event log.

    Each row is one session. Per-user revenue is apportioned across that
    user's sessions (so summing sessions recovers user revenue), and exactly
    one session per converting user is flagged is_conversion=1. This is the
    raw grain the pipeline ingests; dbt re-aggregates it to per-user metrics,
    demonstrating event-data modeling.
    """
    n = len(users_out)
    # Sessions per user (>=2), loosely tied to prior engagement.
    n_sessions = np.clip(users_out["pre_sessions"].to_numpy() // 1 + 2, 2, 14)
    total_rows = int(n_sessions.sum())

    uid = users_out["user_id"].to_numpy()
    exp_day = users_out["exposure_day"].to_numpy()
    converted = users_out["converted"].to_numpy()
    user_rev = users_out["user_revenue"].to_numpy()
    latency = users_out["latency_ms"].to_numpy()

    out_uid = np.empty(total_rows, dtype=np.int64)
    out_day = np.empty(total_rows, dtype=np.int64)
    out_rev = np.empty(total_rows, dtype=np.float64)
    out_lat = np.empty(total_rows, dtype=np.float64)
    out_conv = np.zeros(total_rows, dtype=np.int64)

    pos = 0
    for i in range(n):
        s = int(n_sessions[i])
        days = rng.integers(exp_day[i], cfg.experiment_days, size=s)
        # apportion revenue across sessions with dirichlet weights (sums to 1)
        w = rng.dirichlet(np.ones(s))
        sl = slice(pos, pos + s)
        out_uid[sl] = uid[i]
        out_day[sl] = days
        out_rev[sl] = user_rev[i] * w
        out_lat[sl] = latency[i] + rng.normal(0, 8, size=s)
        if converted[i] == 1:
            out_conv[pos] = 1  # flag one session as the conversion
        pos += s

    ev = pd.DataFrame({
        "user_id": out_uid,
        "event_day": out_day,
        "session_revenue": out_rev.round(4),
        "latency_ms": np.clip(out_lat, 30, None).round(1),
        "is_conversion": out_conv,
    })
    return ev


def build_ground_truth(cfg: ExperimentConfig, users_out: pd.DataFrame) -> dict:
    is_new = users_out["tenure"] == "new"
    share_new = is_new.mean()
    avg_conv_lift = (share_new * cfg.conv_lift_new
                     + (1 - share_new) * cfg.conv_lift_returning)
    return {
        "design": {
            "n_users": int(cfg.n_users),
            "treatment_share": cfg.treatment_share,
            "experiment_days": cfg.experiment_days,
            "share_new_users_actual": round(float(share_new), 4),
        },
        "true_effects": {
            "conversion_abs_lift_overall": round(float(avg_conv_lift), 5),
            "conversion_abs_lift_new": cfg.conv_lift_new,
            "conversion_abs_lift_returning": cfg.conv_lift_returning,
            "revenue_abs_lift": cfg.revenue_lift,
            "latency_true_effect_ms": cfg.latency_true_effect_ms,
        },
        "notes": "Analysis estimates should recover these within their CIs.",
    }


def main(out_dir: str = "data", **overrides) -> None:
    cfg = ExperimentConfig(**overrides)
    rng = _rng(cfg.seed)

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    users = generate_users(cfg, rng)
    users_out = assign_outcomes(cfg, users, rng)
    events = explode_to_events(users_out, cfg, rng)
    ground_truth = build_ground_truth(cfg, users_out)

    # Raw tables the pipeline ingests. Drop the latent column.
    assignments = users_out.drop(
        columns=["_z", "converted", "user_revenue", "latency_ms"])

    assignments.to_parquet(out_path / "assignments.parquet", index=False)
    events.to_parquet(out_path / "events.parquet", index=False)
    with open(out_path / "ground_truth.json", "w") as f:
        json.dump(ground_truth, f, indent=2)

    # Small committable samples so the repo shows data shape without the bulk.
    assignments.head(200).to_csv(out_path / "sample_assignments.csv", index=False)
    events.head(500).to_csv(out_path / "sample_events.csv", index=False)

    print(f"Wrote {len(assignments):,} assignments and {len(events):,} events "
          f"to {out_path}/")
    print(f"Variant split:\n{assignments['variant'].value_counts().to_string()}")
    print(f"Ground truth: {json.dumps(ground_truth['true_effects'], indent=2)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate synthetic A/B test data.")
    ap.add_argument("--out-dir", default="data")
    ap.add_argument("--n-users", type=int, default=60_000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--treatment-share", type=float, default=0.50)
    args = ap.parse_args()
    main(out_dir=args.out_dir, n_users=args.n_users, seed=args.seed,
         treatment_share=args.treatment_share)
