import plotly.graph_objects as go
import streamlit as st

import ui
from data import load

ui.page("Sales", "Department report", "What we sold, where, and through which channel. Cancelled orders are excluded.")
window = ui.date_filter()

sales = load("mart_sales_daily")
with st.sidebar:
    channels = st.multiselect("Channel", sorted(sales["channel"].unique()), format_func=ui.nice)
    regions = st.multiselect("Region", sorted(sales["ship_region"].unique()))


def filtered(frame):
    if channels:
        frame = frame[frame["channel"].isin(channels)]
    if regions:
        frame = frame[frame["ship_region"].isin(regions)]
    return frame


now = filtered(ui.in_range(sales, "order_date", window))
prev = filtered(ui.in_range(sales, "order_date", ui.previous_window(window)))

items = load("fact_order_items")
items = items[~items["is_cancelled"]]
items_now = ui.in_range(items, "order_date", window)
if channels:
    items_now = items_now[items_now["channel"].isin(channels)]
if regions:
    items_now = items_now[items_now["ship_region"].isin(regions)]
orders_now = items_now["order_id"].nunique()
orders_prev = prev["orders"].sum()

net, net_prev = now["net_sales"].sum(), prev["net_sales"].sum()
c = st.columns(5)
c[0].metric("Net sales", ui.money(net), ui.delta(net, net_prev), border=True)
c[1].metric("Orders", ui.number(orders_now), border=True)
c[2].metric("Units sold", ui.number(now["units"].sum()), ui.delta(now["units"].sum(), prev["units"].sum()), border=True)
c[3].metric("Avg order value", ui.money(net / orders_now if orders_now else None), border=True)
c[4].metric("Discount rate", ui.pct(now["discounts"].sum() / now["gross_sales"].sum() if len(now) else None),
            border=True)

left, right = st.columns([3, 2])
with left:
    trend = now.groupby(["order_date", "channel"], as_index=False)["net_sales"].sum()
    fig = go.Figure()
    for channel, color in ui.color_map("channel", trend["channel"].unique()).items():
        part = trend[trend["channel"] == channel]
        if part.empty:
            continue
        fig.add_scatter(x=part["order_date"], y=part["net_sales"], name=ui.nice(channel), mode="lines",
                        line_color=color, hovertemplate=f"{ui.nice(channel)}: $%{{y:,.0f}}<extra></extra>")
    fig.update_layout(title="Net sales per day by channel", yaxis_tickprefix="$", hovermode="x unified")
    st.plotly_chart(ui.style(fig), width="stretch")
with right:
    category = now.groupby("category")["net_sales"].sum().sort_values()
    fig = go.Figure(go.Bar(
        x=category.values, y=category.index, orientation="h",
        marker_color=[ui.COLORS["category"].get(v) for v in category.index],
        text=[ui.money(v) for v in category.values], textposition="outside", cliponaxis=False,
        hovertemplate="%{y}: $%{x:,.0f}<extra></extra>"))
    fig.update_layout(title="Net sales by category", xaxis_visible=False)
    ui.bar_room(fig, category.values)
    st.plotly_chart(ui.style(fig, legend=False), width="stretch")

left, right = st.columns([2, 3])
with left:
    grid = now.pivot_table(index="ship_region", columns="category", values="net_sales", aggfunc="sum").fillna(0)
    fig = go.Figure(go.Heatmap(
        z=grid.values, x=grid.columns, y=grid.index, colorscale=[[i / 6, c] for i, c in enumerate(ui.SEQUENTIAL)],
        xgap=2, ygap=2, colorbar=dict(tickprefix="$", thickness=10),
        hovertemplate="%{y} · %{x}<br>$%{z:,.0f}<extra></extra>"))
    fig.update_layout(title="Region × category net sales")
    st.plotly_chart(ui.style(fig, legend=False), width="stretch")
with right:
    st.markdown("**Top products in the period**")
    top = (items_now.groupby(["product_name", "category"], as_index=False)
           .agg(units=("quantity", "sum"), net_sales=("net_amount", "sum"), gross_profit=("gross_profit", "sum"),
                returned=("is_returned_line", "sum"))
           .sort_values("net_sales", ascending=False).head(12))
    top["margin"] = top["gross_profit"] / top["net_sales"]
    st.dataframe(
        top[["product_name", "category", "units", "net_sales", "margin", "returned"]],
        hide_index=True, width="stretch", height=330,
        column_config={
            "product_name": "Product", "category": "Category", "units": st.column_config.NumberColumn("Units"),
            "net_sales": st.column_config.ProgressColumn("Net sales", format="$%.0f",
                                                         max_value=float(top["net_sales"].max() or 1)),
            "margin": st.column_config.NumberColumn("Margin", format="percent"),
            "returned": st.column_config.NumberColumn("Lines returned"),
        })

with st.expander("Product performance (all time)"):
    st.dataframe(load("mart_product_performance").sort_values("net_sales", ascending=False), hide_index=True,
                 width="stretch",
                 column_config={"margin_pct": st.column_config.NumberColumn("Margin", format="percent"),
                                "return_rate": st.column_config.NumberColumn("Return rate", format="percent"),
                                "net_sales": st.column_config.NumberColumn("Net sales", format="$%.0f"),
                                "gross_profit": st.column_config.NumberColumn("Gross profit", format="$%.0f")})
