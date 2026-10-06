"""Executive overview: the landing page of the multi-page department report."""
import plotly.graph_objects as go
import streamlit as st

import ui
from data import load

ui.page("Executive overview", "Northstar Commerce · Company",
        "Headline numbers from every department, built from the Gold layer of the lakehouse.")
window = ui.date_filter()
before = ui.previous_window(window)

finance = load("mart_finance_daily")
orders = load("fact_orders")
now, prev = ui.in_range(finance, "date", window), ui.in_range(finance, "date", before)
o_now, o_prev = ui.in_range(orders, "order_date", window), ui.in_range(orders, "order_date", before)


def ops(frame):
    delivered = frame[frame["delivered_at"].notna()]
    on_time = 1 - delivered["is_late_delivery"].mean() if len(delivered) else None
    return on_time


net, net_prev = now["net_revenue"].sum(), prev["net_revenue"].sum()
count, count_prev = len(o_now), len(o_prev)
aov = o_now["order_total"].mean()
margin = now["gross_profit"].sum() / net if net else None
returns = (o_now["return_requested_at"].notna().sum() / o_now["delivered_at"].notna().sum()
           if o_now["delivered_at"].notna().sum() else None)

c = st.columns(6)
c[0].metric("Net revenue", ui.money(net), ui.delta(net, net_prev), border=True)
c[1].metric("Orders", ui.number(count), ui.delta(count, count_prev), border=True)
c[2].metric("Avg order value", ui.money(aov), ui.delta(aov, o_prev["order_total"].mean()), border=True)
c[3].metric("Gross margin", ui.pct(margin), border=True)
c[4].metric("On-time delivery", ui.pct(ops(o_now)), border=True)
c[5].metric("Return rate", ui.pct(returns), delta_color="inverse", border=True)

left, right = st.columns([3, 2])
with left:
    daily = now.sort_values("date")
    fig = go.Figure(go.Scatter(x=daily["date"], y=daily["net_revenue"], mode="lines", name="Net revenue",
                               line_color=ui.SERIES[0], fill="tozeroy", fillcolor="rgba(42,120,214,0.08)",
                               hovertemplate="%{x|%a %d %b}<br>$%{y:,.0f}<extra></extra>"))
    fig.update_layout(title="Net revenue per day", yaxis_tickprefix="$", hovermode="x")
    st.plotly_chart(ui.style(fig, legend=False), width="stretch")
with right:
    by_channel = (o_now[o_now["order_status"] != "cancelled"].groupby("channel")["merchandise_amount"].sum()
                  .sort_values())
    fig = go.Figure(go.Bar(
        x=by_channel.values, y=[ui.nice(v) for v in by_channel.index], orientation="h",
        marker_color=[ui.COLORS["channel"].get(v, ui.SERIES[0]) for v in by_channel.index],
        text=[ui.money(v) for v in by_channel.values], textposition="outside", cliponaxis=False,
        hovertemplate="%{y}: $%{x:,.0f}<extra></extra>"))
    fig.update_layout(title="Sales by channel", xaxis_visible=False)
    ui.bar_room(fig, by_channel.values)
    st.plotly_chart(ui.style(fig, legend=False), width="stretch")

st.subheader("Departments")
pages = [
    ("pages/1_Sales.py", "Sales", "📈", "Revenue, products, channels and regions"),
    ("pages/2_Marketing.py", "Marketing", "📣", "Acquisition, campaigns, cohorts and RFM segments"),
    ("pages/3_Operations.py", "Operations", "🚚", "Fulfilment speed, carriers and open backlog"),
    ("pages/4_Finance.py", "Finance", "💰", "Revenue bridge, refunds, margin and payments"),
    ("pages/5_Customer_Service.py", "Customer service", "🎧", "Returns, ratings and the attention queue"),
    ("pages/6_Data_Platform.py", "Data platform", "🛠️", "Pipeline health, data quality and lineage"),
]
cols = st.columns(3)
for i, (path, label, icon, text) in enumerate(pages):
    with cols[i % 3].container(border=True):
        st.page_link(path, label=f"**{label}**", icon=icon)
        st.caption(text)

dq = load("dq_check_results")
if not dq.empty:
    latest = dq[dq["checked_at"] == dq["checked_at"].max()]
    failed = latest[~latest["passed"]]
    if failed.empty:
        st.success(f"All {len(latest)} data-quality checks passed on the latest pipeline run.", icon="✅")
    else:
        st.warning(f"{len(failed)} of {len(latest)} data-quality checks need attention: "
                   + ", ".join(failed["check_name"]), icon="⚠️")
