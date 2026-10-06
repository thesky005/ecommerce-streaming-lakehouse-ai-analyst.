import plotly.graph_objects as go
import streamlit as st

import ui
from data import load

ui.page("Finance", "Department report",
        "From gross bookings to gross profit. Bookings count paid orders by order date; refunds by the date issued.")
window = ui.date_filter()
before = ui.previous_window(window)

finance = load("mart_finance_daily")
now, prev = ui.in_range(finance, "date", window), ui.in_range(finance, "date", before)
t, p = now.sum(numeric_only=True), prev.sum(numeric_only=True)

c = st.columns(6)
c[0].metric("Gross sales", ui.money(t["gross_sales"]), ui.delta(t["gross_sales"], p["gross_sales"]), border=True)
c[1].metric("Discounts", ui.money(t["discounts"]), border=True)
c[2].metric("Refunds", ui.money(t["refunds"]), ui.delta(t["refunds"], p["refunds"]), delta_color="inverse",
            border=True)
c[3].metric("Net revenue", ui.money(t["net_revenue"]), ui.delta(t["net_revenue"], p["net_revenue"]), border=True)
c[4].metric("Gross profit", ui.money(t["gross_profit"]), ui.delta(t["gross_profit"], p["gross_profit"]), border=True)
c[5].metric("Gross margin", ui.pct(t["gross_profit"] / t["net_revenue"] if t["net_revenue"] else None), border=True)

left, right = st.columns([2, 3])
with left:
    steps = [("Gross sales", t["gross_sales"], "absolute"), ("Discounts", -t["discounts"], "relative"),
             ("Shipping", t["shipping_revenue"], "relative"), ("Refunds", -t["refunds"], "relative"),
             ("Net revenue", t["net_revenue"], "total"), ("COGS", -t["cogs"], "relative"),
             ("Gross profit", t["gross_profit"], "total")]
    fig = go.Figure(go.Waterfall(
        x=[s[0] for s in steps], y=[s[1] for s in steps], measure=[s[2] for s in steps],
        text=[ui.money(abs(s[1])) for s in steps], textposition="outside", cliponaxis=False,
        increasing_marker_color=ui.SERIES[2], decreasing_marker_color=ui.SERIES[7],
        totals_marker_color=ui.SERIES[0], connector_line_color=ui.AXIS,
        hovertemplate="%{x}: $%{y:,.0f}<extra></extra>"))
    fig.update_layout(title="Revenue bridge for the period", yaxis_tickprefix="$")
    st.plotly_chart(ui.style(fig, height=380, legend=False), width="stretch")
with right:
    daily = now.sort_values("date")
    fig = go.Figure()
    for column, name, color in (("net_revenue", "Net revenue", ui.SERIES[0]),
                                ("gross_profit", "Gross profit", ui.SERIES[2]),
                                ("refunds", "Refunds", ui.SERIES[7])):
        fig.add_scatter(x=daily["date"], y=daily[column], name=name, mode="lines", line_color=color,
                        hovertemplate=f"{name}: $%{{y:,.0f}}<extra></extra>")
    fig.update_layout(title="Daily revenue, profit and refunds", yaxis_tickprefix="$", hovermode="x unified")
    st.plotly_chart(ui.style(fig, height=380), width="stretch")

left, right = st.columns([3, 2])
with left:
    st.markdown("**Payment methods (all time)**")
    methods_table = load("mart_payment_methods").sort_values("collected_amount", ascending=False)
    methods_table["payment_method"] = methods_table["payment_method"].map(ui.nice)
    st.dataframe(methods_table, hide_index=True,
                 width="stretch",
                 column_config={"payment_method": "Method", "orders": "Orders",
                                "orders_with_failure": "Orders with a failure", "failed_attempts": "Failed attempts",
                                "lost_orders": "Lost to failure",
                                "collected_amount": st.column_config.NumberColumn("Collected", format="$%.0f"),
                                "avg_order_value": st.column_config.NumberColumn("Avg order", format="$%.2f"),
                                "failure_rate": st.column_config.NumberColumn("Failure rate", format="percent")})
with right:
    methods = load("mart_payment_methods").sort_values("failure_rate")
    fig = go.Figure(go.Bar(
        x=methods["failure_rate"] * 100, y=[ui.nice(m) for m in methods["payment_method"]], orientation="h",
        marker_color=ui.SERIES[1], text=[f"{v * 100:.1f}%" for v in methods["failure_rate"]],
        textposition="outside", cliponaxis=False, hovertemplate="%{y}: %{x:.2f}%<extra></extra>"))
    fig.update_layout(title="Payment failure rate by method", xaxis_visible=False)
    ui.bar_room(fig, methods["failure_rate"] * 100)
    st.plotly_chart(ui.style(fig, height=300, legend=False), width="stretch")

with st.expander("Daily finance ledger"):
    st.dataframe(now.sort_values("date", ascending=False), hide_index=True, width="stretch",
                 column_config={"date": st.column_config.DateColumn("Date"),
                                "gross_margin_pct": st.column_config.NumberColumn("Margin", format="percent")})
