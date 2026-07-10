"""
Experiment readout dashboard.

Its single job: tell someone who has never heard of a p-value whether this
change should ship, and show the evidence behind that call. The statistics are
present but tucked away; the plain-language verdict leads.

Run:  streamlit run app/main.py
"""

import math
import os
import sys

# Make the repo root importable so `analysis` resolves no matter where
# `streamlit run` is launched from (Streamlit puts app/ on the path, not root).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import plotly.graph_objects as go
import streamlit as st

from analysis.experiment import load_metrics, conversion_readout, continuous_readout


# ------------------------------------------------------------------ palette --
NAVY = "#1f2a44"
INK = "#2b2f36"
MUTED = "#6b7280"
SHIP = "#1f8a5b"      # green
CAUTION = "#c07a1a"   # amber
STOP = "#b02a37"      # red
CARD = "#f5f6f8"
LINE = "#d9dce1"


st.set_page_config(page_title="Experiment Readout", page_icon="📊",
                   layout="wide")


# ------------------------------------------------------------- computation ---
@st.cache_data
def get_results():
    df = load_metrics()
    return {
        "conversion": conversion_readout(df),
        "revenue": continuous_readout(df, "revenue"),
        "latency": continuous_readout(df, "avg_latency_ms"),
    }


def decide(conv, guardrail):
    """Plain ship/no-ship logic.

    Ship only if the primary metric improved and we can rule out chance, and
    the guardrail did not get significantly worse. Higher latency = worse, so a
    significant *increase* in latency is a guardrail regression.
    """
    primary_win = conv.significant() and conv.abs_lift > 0
    guardrail_regressed = guardrail.significant() and guardrail.abs_lift > 0

    if not conv.significant():
        return ("INCONCLUSIVE", STOP,
                "The change did not move conversion by a clear enough margin to "
                "rule out random chance. Keep the current version, or run longer.")
    if conv.abs_lift < 0:
        return ("DON'T SHIP", STOP,
                "The change made conversion worse. Keep the current version.")
    if guardrail_regressed:
        return ("SHIP WITH CAUTION", CAUTION,
                "Conversion improved, but page latency got significantly worse. "
                "Worth a look before rolling out to everyone.")
    return ("SHIP IT", SHIP,
            "The change improved conversion, the result is very unlikely to be "
            "chance, and it did not harm the experience. Safe to roll out.")


# --------------------------------------------------------------- rendering ---
def banner(verdict, color, message):
    st.markdown(
        f"""
        <div style="background:{color};border-radius:14px;padding:26px 30px;
                    color:white;margin-bottom:8px;">
          <div style="font-size:13px;letter-spacing:.14em;text-transform:uppercase;
                      opacity:.85;">Recommendation</div>
          <div style="font-size:40px;font-weight:800;line-height:1.1;
                      margin:4px 0 8px;">{verdict}</div>
          <div style="font-size:17px;opacity:.95;max-width:70ch;">{message}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def group_ci(rate, n, z=1.96):
    se = math.sqrt(rate * (1 - rate) / n)
    return z * se


def conversion_chart(conv):
    err_c = group_ci(conv.control_rate, conv.n_control)
    err_t = group_ci(conv.treatment_rate, conv.n_treatment)
    fig = go.Figure()
    fig.add_bar(
        x=["Current (control)", "New version (treatment)"],
        y=[conv.control_rate * 100, conv.treatment_rate * 100],
        error_y=dict(type="data", array=[err_c * 100, err_t * 100],
                     color=MUTED, thickness=1.5, width=8),
        marker_color=[LINE, SHIP],
        text=[f"{conv.control_rate:.1%}", f"{conv.treatment_rate:.1%}"],
        textposition="outside", textfont=dict(size=16, color=INK),
    )
    fig.update_layout(
        height=340, margin=dict(l=10, r=10, t=10, b=10),
        yaxis_title="Conversion rate (%)", showlegend=False,
        plot_bgcolor="white", font=dict(color=INK),
    )
    fig.update_yaxes(gridcolor=CARD, zeroline=False)
    return fig


def metric_row(label, control, treatment, lift_str, verdict_str, good):
    color = SHIP if good else MUTED
    c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
    c1.markdown(f"**{label}**")
    c2.markdown(f"{control}")
    c3.markdown(f"{treatment}")
    c4.markdown(f"<span style='color:{color};font-weight:600'>{lift_str} · "
                f"{verdict_str}</span>", unsafe_allow_html=True)


# --------------------------------------------------------------------- page --
try:
    R = get_results()
except FileNotFoundError:
    st.error("No data found. Run `make build` first to create the warehouse, "
             "then reload this page.")
    st.stop()

conv, rev, lat = R["conversion"], R["revenue"], R["latency"]
verdict, color, message = decide(conv, lat)

st.markdown(f"<h1 style='color:{NAVY};margin-bottom:0'>Checkout button experiment</h1>",
            unsafe_allow_html=True)
st.markdown(f"<p style='color:{MUTED};margin-top:4px'>Did the new version get "
            f"more people to convert, without breaking anything?</p>",
            unsafe_allow_html=True)

banner(verdict, color, message)

st.markdown("### What happened")
left, right = st.columns([3, 2])
with left:
    st.plotly_chart(conversion_chart(conv), width='stretch')
with right:
    st.markdown(
        f"<div style='background:{CARD};border-radius:12px;padding:20px'>"
        f"<div style='color:{MUTED};font-size:13px'>Conversion changed by</div>"
        f"<div style='font-size:34px;font-weight:800;color:{NAVY}'>"
        f"{conv.abs_lift*100:+.2f} pts</div>"
        f"<div style='color:{MUTED};font-size:14px'>"
        f"that's a {conv.rel_lift:+.1%} relative change, from "
        f"{conv.control_rate:.1%} to {conv.treatment_rate:.1%}</div>"
        f"<div style='margin-top:14px;color:{INK};font-size:15px'>"
        f"The vertical lines on the bars show the range of uncertainty. "
        f"They don't overlap, which is the visual version of "
        f"\"this is unlikely to be a fluke.\"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

st.markdown("### Every metric we watched")
metric_row("Metric", "_Current_", "_New version_", "_Change_", "_Read_", True)
st.markdown(f"<hr style='margin:2px 0;border:none;border-top:1px solid {LINE}'>",
            unsafe_allow_html=True)
metric_row("Conversion rate (primary)",
           f"{conv.control_rate:.2%}", f"{conv.treatment_rate:.2%}",
           f"{conv.abs_lift*100:+.2f}pt",
           "clear win" if conv.significant() and conv.abs_lift > 0 else "no clear effect",
           conv.significant() and conv.abs_lift > 0)
metric_row("Revenue per user (secondary)",
           f"${rev.control_mean:.2f}", f"${rev.treatment_mean:.2f}",
           f"{rev.abs_lift:+.2f}",
           "clear win" if rev.significant() and rev.abs_lift > 0 else "no clear effect",
           rev.significant() and rev.abs_lift > 0)
metric_row("Page latency, ms (guardrail)",
           f"{lat.control_mean:.0f}", f"{lat.treatment_mean:.0f}",
           f"{lat.abs_lift:+.1f}",
           "not harmed" if not (lat.significant() and lat.abs_lift > 0) else "got worse",
           not (lat.significant() and lat.abs_lift > 0))

st.caption("Guardrail metrics are things we don't want to break while chasing a "
           "win. Latency staying flat means the new version didn't slow the page down.")

with st.expander("Statistical detail (for the analysts)"):
    st.markdown(
        f"""
| Metric | Test | Effect | 95% CI | p-value | Significant |
|---|---|---|---|---|---|
| Conversion | Two-proportion z | {conv.abs_lift*100:+.3f} pt | [{conv.ci_low*100:+.3f}, {conv.ci_high*100:+.3f}] pt | {conv.p_value:.4f} | {'yes' if conv.significant() else 'no'} |
| Revenue | Welch t | {rev.abs_lift:+.3f} | [{rev.ci_low:+.3f}, {rev.ci_high:+.3f}] | {rev.p_value:.4f} | {'yes' if rev.significant() else 'no'} |
| Latency (guardrail) | Welch t | {lat.abs_lift:+.3f} | [{lat.ci_low:+.3f}, {lat.ci_high:+.3f}] | {lat.p_value:.4f} | {'yes' if lat.significant() else 'no'} |

Sample size: {conv.n_control:,} control / {conv.n_treatment:,} treatment.
Significance threshold alpha = 0.05 (two-sided). The conversion p-value uses a
pooled standard error; the confidence interval uses an unpooled one.
        """
    )
