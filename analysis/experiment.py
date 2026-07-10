"""
Analysis layer — Phase 3, step 1: the two-proportion test.

This is the single most fundamental A/B test computation: given a binary
outcome (converted / didn't) measured in two groups, decide whether the
difference in conversion rate is real or could plausibly be noise.

Reads the gold mart (`experiment_metrics`) produced by dbt, so the pipeline
is: raw parquet -> dbt -> experiment_metrics -> this analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
from scipy import stats


DB_PATH = Path(__file__).resolve().parents[1] / "dbt" / "dev.duckdb"


@dataclass
class ProportionResult:
    control_rate: float
    treatment_rate: float
    abs_lift: float          # treatment_rate - control_rate
    rel_lift: float          # abs_lift / control_rate
    se_diff: float           # standard error of the difference (unpooled, for CI)
    ci_low: float
    ci_high: float
    z_stat: float            # test statistic (pooled SE, for the p-value)
    p_value: float
    n_control: int
    n_treatment: int

    def significant(self, alpha: float = 0.05) -> bool:
        return self.p_value < alpha


def two_proportion_test(x_control: int, n_control: int,
                        x_treatment: int, n_treatment: int,
                        alpha: float = 0.05) -> ProportionResult:
    """Two-sided two-proportion z-test.

    x_* = number of successes (conversions), n_* = group size.

    Two different standard errors are used on purpose:
      * the p-value tests H0: rates are equal, so it uses the POOLED SE
        (best estimate of the shared rate under the null),
      * the confidence interval describes the difference we actually observed,
        so it uses the UNPOOLED SE (each group's own rate).
    """
    p_c = x_control / n_control
    p_t = x_treatment / n_treatment
    diff = p_t - p_c

    # Unpooled SE -> confidence interval for the observed difference.
    se_unpooled = ((p_c * (1 - p_c) / n_control)
                   + (p_t * (1 - p_t) / n_treatment)) ** 0.5
    z_crit = stats.norm.ppf(1 - alpha / 2)
    ci_low = diff - z_crit * se_unpooled
    ci_high = diff + z_crit * se_unpooled

    # Pooled SE -> hypothesis test / p-value.
    p_pool = (x_control + x_treatment) / (n_control + n_treatment)
    se_pooled = (p_pool * (1 - p_pool)
                 * (1 / n_control + 1 / n_treatment)) ** 0.5
    z_stat = diff / se_pooled
    p_value = 2 * (1 - stats.norm.cdf(abs(z_stat)))

    return ProportionResult(
        control_rate=p_c, treatment_rate=p_t, abs_lift=diff,
        rel_lift=diff / p_c if p_c else float("nan"),
        se_diff=se_unpooled, ci_low=ci_low, ci_high=ci_high,
        z_stat=z_stat, p_value=p_value,
        n_control=n_control, n_treatment=n_treatment,
    )


@dataclass
class MeanResult:
    control_mean: float
    treatment_mean: float
    abs_lift: float
    rel_lift: float
    ci_low: float
    ci_high: float
    t_stat: float
    p_value: float
    n_control: int
    n_treatment: int

    def significant(self, alpha: float = 0.05) -> bool:
        return self.p_value < alpha


def two_sample_ttest(control_values, treatment_values,
                     alpha: float = 0.05) -> MeanResult:
    """Welch's two-sample t-test for a continuous metric (unequal variances).

    Used for revenue (secondary) and latency (guardrail). Welch is the safe
    default: it does not assume the two groups have equal variance.
    """
    import numpy as np

    c = np.asarray(control_values, dtype=float)
    t = np.asarray(treatment_values, dtype=float)
    n_c, n_t = len(c), len(t)
    m_c, m_t = c.mean(), t.mean()
    v_c, v_t = c.var(ddof=1), t.var(ddof=1)
    diff = m_t - m_c

    se = (v_c / n_c + v_t / n_t) ** 0.5
    # Welch-Satterthwaite degrees of freedom
    df = (v_c / n_c + v_t / n_t) ** 2 / (
        (v_c / n_c) ** 2 / (n_c - 1) + (v_t / n_t) ** 2 / (n_t - 1))
    t_stat = diff / se
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df))
    t_crit = stats.t.ppf(1 - alpha / 2, df)

    return MeanResult(
        control_mean=m_c, treatment_mean=m_t, abs_lift=diff,
        rel_lift=diff / m_c if m_c else float("nan"),
        ci_low=diff - t_crit * se, ci_high=diff + t_crit * se,
        t_stat=t_stat, p_value=p_value,
        n_control=n_c, n_treatment=n_t,
    )


def continuous_readout(df, column: str) -> MeanResult:
    c = df.loc[df["variant"] == "control", column]
    t = df.loc[df["variant"] == "treatment", column]
    return two_sample_ttest(c, t)


def load_metrics(db_path: Path = DB_PATH):
    """Load the per-user gold mart from the DuckDB warehouse."""
    if not db_path.exists():
        raise FileNotFoundError(
            f"{db_path} not found. Run `make build` first to create the mart."
        )
    con = duckdb.connect(str(db_path), read_only=True)
    df = con.sql("select * from main.experiment_metrics").df()
    con.close()
    return df


def conversion_readout(df) -> ProportionResult:
    g = df.groupby("variant")["converted"].agg(["sum", "count"])
    res = two_proportion_test(
        x_control=int(g.loc["control", "sum"]),
        n_control=int(g.loc["control", "count"]),
        x_treatment=int(g.loc["treatment", "sum"]),
        n_treatment=int(g.loc["treatment", "count"]),
    )
    return res


if __name__ == "__main__":
    df = load_metrics()
    r = conversion_readout(df)
    print("CONVERSION — two-proportion test")
    print("-" * 44)
    print(f"control    : {r.control_rate:7.4%}  (n={r.n_control:,})")
    print(f"treatment  : {r.treatment_rate:7.4%}  (n={r.n_treatment:,})")
    print(f"abs lift   : {r.abs_lift:+.4%}   (relative {r.rel_lift:+.1%})")
    print(f"95% CI     : [{r.ci_low:+.4%}, {r.ci_high:+.4%}]")
    print(f"z / p-value: {r.z_stat:.3f} / {r.p_value:.5f}")
    verdict = "SIGNIFICANT — reject 'no effect'" if r.significant() \
        else "not significant — can't rule out noise"
    print(f"verdict    : {verdict}")
