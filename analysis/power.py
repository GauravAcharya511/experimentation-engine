"""
Analysis layer — Phase 3, step 2: power and sample size.

Two directions of the same relationship:

  required_sample_size(...)  -> BEFORE running: how many users per arm do I
                                need to detect an effect of size `mde`?
  achieved_power(...)        -> AFTER running (or when planning with a fixed n):
                                given this many users, what's my probability of
                                detecting an effect of size `mde`?

The design lever to internalize: required n scales with 1 / mde**2, so halving
the effect you want to catch roughly quadruples the users you need.
"""

from __future__ import annotations

import math

from scipy import stats


def required_sample_size(baseline_rate: float, mde: float,
                         alpha: float = 0.05, power: float = 0.80) -> int:
    """Users PER ARM needed to detect an absolute lift `mde` on a binary metric.

    baseline_rate : control conversion rate, e.g. 0.12
    mde           : absolute minimum detectable effect, e.g. 0.008 (=0.8pp)
    """
    z_alpha = stats.norm.ppf(1 - alpha / 2)   # two-sided
    z_beta = stats.norm.ppf(power)
    p1 = baseline_rate
    p2 = baseline_rate + mde
    p_bar = (p1 + p2) / 2
    numerator = (z_alpha * math.sqrt(2 * p_bar * (1 - p_bar))
                 + z_beta * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    return math.ceil(numerator / mde ** 2)


def achieved_power(baseline_rate: float, mde: float, n_per_arm: int,
                   alpha: float = 0.05) -> float:
    """Probability of detecting an absolute lift `mde` given `n_per_arm` users."""
    z_alpha = stats.norm.ppf(1 - alpha / 2)
    p1 = baseline_rate
    p2 = baseline_rate + mde
    se = math.sqrt(p1 * (1 - p1) / n_per_arm + p2 * (1 - p2) / n_per_arm)
    # non-centrality: how many SEs the true effect sits from zero
    ncp = mde / se
    # power = P(reject | effect real) for a two-sided test
    return float(stats.norm.cdf(ncp - z_alpha) + stats.norm.cdf(-ncp - z_alpha))


def runtime_days(n_per_arm: int, daily_eligible_users: int,
                 n_arms: int = 2) -> float:
    """How long to run: total users needed / users arriving per day."""
    return (n_per_arm * n_arms) / daily_eligible_users


if __name__ == "__main__":
    baseline = 0.12
    mde = 0.008
    n = required_sample_size(baseline, mde)
    print("POWER & SAMPLE SIZE")
    print("-" * 44)
    print(f"baseline rate : {baseline:.1%}")
    print(f"target MDE    : {mde:.1%}  (absolute lift to detect)")
    print(f"alpha / power : 0.05 / 0.80")
    print(f"required n/arm: {n:,}")
    print(f"actually ran  : 30,000/arm -> "
          f"power = {achieved_power(baseline, mde, 30_000):.1%}")
    print()
    print("Sample size vs. effect size (the 1/mde^2 relationship):")
    for m in (0.020, 0.010, 0.008, 0.005):
        print(f"  MDE {m:>5.1%}  ->  {required_sample_size(baseline, m):>8,} / arm")
    print()
    # A design example: how long would this take at a given traffic level?
    daily = 8_000
    days = runtime_days(n, daily)
    print(f"If {daily:,} eligible users/day, runtime ~ {days:.1f} days "
          f"({math.ceil(days)} to be safe).")
