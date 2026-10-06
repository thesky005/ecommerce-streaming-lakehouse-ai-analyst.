"""Shared layout, filters, number formats and chart styling for every report page."""
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data import lake_ready, load

# Reference categorical palette, assigned in fixed order. Each entity keeps its color on every page.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
INK, INK_2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
GOOD, WARNING, CRITICAL = "#0ca30c", "#fab219", "#d03b3b"

COLORS = {
    "channel": {"web": SERIES[0], "mobile_app": SERIES[1], "marketplace": SERIES[2]},
    "category": {"Electronics": SERIES[0], "Apparel": SERIES[1], "Home & Kitchen": SERIES[2],
                 "Beauty": SERIES[3], "Sports & Outdoors": SERIES[4], "Books": SERIES[5]},
    "traffic_source": {"organic_search": SERIES[0], "paid_search": SERIES[1], "direct": SERIES[2],
                       "social": SERIES[3], "email": SERIES[4], "affiliate": SERIES[5]},
    "warehouse_id": {"WH-RENO": SERIES[0], "WH-COLUMBUS": SERIES[1], "WH-DALLAS": SERIES[2], "WH-NEWARK": SERIES[3]},
    "carrier": {"SwiftShip": SERIES[0], "ParcelPro": SERIES[1], "EconoPost": SERIES[2]},
    "ship_region": {"West": SERIES[0], "Midwest": SERIES[1], "South": SERIES[2], "Northeast": SERIES[3]},
}

LABELS = {
    "web": "Web", "mobile_app": "Mobile app", "marketplace": "Marketplace",
    "organic_search": "Organic search", "paid_search": "Paid search", "direct": "Direct",
    "social": "Social", "email": "Email", "affiliate": "Affiliate",
}

CSS = """
<style>
  .block-container { padding-top: 3.5rem; max-width: 1300px; }
  [data-testid="stMetric"] { background: #fcfcfb; border-radius: 10px; }
  [data-testid="stMetricLabel"] p { color: #52514e; font-size: 0.82rem; }
  .page-eyebrow { color: #898781; font-size: 0.75rem; letter-spacing: .08em; text-transform: uppercase;
                  margin-bottom: -0.6rem; }
  .status { display:inline-block; padding: 2px 9px; border-radius: 999px; font-size: 0.78rem; font-weight: 600; }
  .status.pass { background:#e7f5e7; color:#006300; } .status.warn { background:#fdf1d6; color:#7a5200; }
  .status.fail { background:#fbe3e3; color:#9b1c1c; }
</style>
"""


def page(title: str, department: str, caption: str) -> None:
    st.set_page_config(page_title=f"{title} · Northstar Commerce", layout="wide", page_icon="📊")
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(f'<div class="page-eyebrow">{department}</div>', unsafe_allow_html=True)
    st.title(title)
    st.caption(caption)
    if not lake_ready():
        st.warning("No Gold data yet. Run the pipeline first: `python scripts/run_local.py --fresh` "
                   "or start the Docker stack and wait for the first Airflow run.")
        st.stop()


def date_filter() -> tuple[pd.Timestamp, pd.Timestamp]:
    """Sidebar date range shared by every page (kept in session state across page switches)."""
    orders = load("fact_orders")
    first, last = orders["order_date"].min().date(), orders["order_date"].max().date()
    saved = st.session_state.get("date_range_value", (first, last))
    start = max(first, min(saved[0], last))
    end = min(last, max(saved[-1], first))
    with st.sidebar:
        st.markdown("**Filters**")
        picked = st.date_input("Order date", value=(start, end), min_value=first, max_value=last,
                               format="YYYY-MM-DD")
        refreshed = load("mart_table_stats")
        if not refreshed.empty:
            st.caption(f"Gold refreshed {refreshed['last_updated'].max():%Y-%m-%d %H:%M} UTC")
        if st.button("Reload data", width="stretch"):
            st.cache_data.clear()
            st.rerun()
    if isinstance(picked, (tuple, list)) and len(picked) == 2:
        st.session_state["date_range_value"] = (picked[0], picked[1])
        start, end = picked
    return pd.Timestamp(start), pd.Timestamp(end)


def in_range(df: pd.DataFrame, column: str, window: tuple[pd.Timestamp, pd.Timestamp]) -> pd.DataFrame:
    return df[(df[column] >= window[0]) & (df[column] <= window[1])]


def previous_window(window: tuple[pd.Timestamp, pd.Timestamp]) -> tuple[pd.Timestamp, pd.Timestamp]:
    length = window[1] - window[0] + pd.Timedelta(days=1)
    return window[0] - length, window[0] - pd.Timedelta(days=1)


def money(value: float) -> str:
    if value is None or pd.isna(value):
        return "–"
    for threshold, suffix in ((1e6, "M"), (1e3, "K")):
        if abs(value) >= threshold:
            scaled = value / threshold
            return f"${scaled:,.0f}{suffix}" if abs(scaled) >= 100 else f"${scaled:,.1f}{suffix}"
    return f"${value:,.0f}"


def pct(value: float, digits: int = 1) -> str:
    return "–" if value is None or pd.isna(value) else f"{value * 100:.{digits}f}%"


def number(value: float) -> str:
    return "–" if value is None or pd.isna(value) else f"{value:,.0f}"


def delta(current: float, previous: float) -> str | None:
    if not previous or pd.isna(previous) or pd.isna(current):
        return None
    return f"{(current - previous) / abs(previous) * 100:+.1f}% vs prior period"


def style(fig: go.Figure, height: int = 340, legend: bool = True) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=36, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=SURFACE,
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', color=INK_2, size=12),
        title=dict(font=dict(size=14, color=INK), x=0, xanchor="left"),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0, title_text=""),
        hoverlabel=dict(bgcolor="white", font_color=INK, bordercolor=GRID),
        bargap=0.25,
    )
    fig.update_xaxes(showgrid=False, linecolor=AXIS, tickfont_color=MUTED, title_font_color=MUTED)
    fig.update_yaxes(gridcolor=GRID, gridwidth=1, zeroline=False, linecolor=AXIS, tickfont_color=MUTED,
                     title_font_color=MUTED)
    fig.update_traces(selector=dict(type="scatter"), line_width=2)
    fig.update_traces(selector=dict(type="bar"), marker_line_width=0)
    return fig


def bar_room(fig: go.Figure, values, horizontal: bool = True) -> go.Figure:
    """Leave space past the longest bar so outside value labels are never clipped."""
    top = max([float(v) for v in values] + [0]) * 1.22 or 1
    return fig.update_xaxes(range=[0, top]) if horizontal else fig.update_yaxes(range=[0, top])


def color_map(dimension: str, values) -> dict:
    known = COLORS.get(dimension, {})
    extra = [v for v in values if v not in known]
    return {**known, **{v: SERIES[(len(known) + i) % len(SERIES)] for i, v in enumerate(extra)}}


def nice(value: str) -> str:
    return LABELS.get(value, str(value).replace("_", " ").capitalize())


def today() -> date:
    return date.today()
