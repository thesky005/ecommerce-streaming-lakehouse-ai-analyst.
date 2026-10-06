import plotly.graph_objects as go
import streamlit as st

import ui
from data import load

ui.page("Marketing", "Department report",
        "Where customers come from, what campaigns return, and how well we keep the customers we win.")
window = ui.date_filter()
before = ui.previous_window(window)

channels = load("mart_marketing_channels")
now, prev = ui.in_range(channels, "order_date", window), ui.in_range(channels, "order_date", before)

new, new_prev = now["new_customers"].sum(), prev["new_customers"].sum()
revenue = now["revenue"].sum()
discount = now["discount_cost"].sum()
paid = now[now["traffic_source"].isin(["paid_search", "social", "affiliate"])]
c = st.columns(5)
c[0].metric("New customers", ui.number(new), ui.delta(new, new_prev), border=True)
c[1].metric("Returning-customer orders", ui.pct(now["returning_orders"].sum() / now["orders"].sum()
                                                 if now["orders"].sum() else None), border=True)
c[2].metric("Campaign revenue", ui.money(now[now["campaign_id"] != "(none)"]["revenue"].sum()), border=True)
c[3].metric("Discount cost", ui.money(discount), ui.delta(discount, prev["discount_cost"].sum()),
            delta_color="inverse", border=True)
c[4].metric("Revenue per $1 discount", f"${revenue / discount:,.1f}" if discount else "–", border=True)

left, right = st.columns(2)
with left:
    by_source = now.groupby("traffic_source", as_index=False).agg(
        revenue=("revenue", "sum"), new_customers=("new_customers", "sum")).sort_values("revenue")
    fig = go.Figure(go.Bar(
        x=by_source["revenue"], y=[ui.nice(v) for v in by_source["traffic_source"]], orientation="h",
        marker_color=[ui.COLORS["traffic_source"].get(v) for v in by_source["traffic_source"]],
        text=[ui.money(v) for v in by_source["revenue"]], textposition="outside", cliponaxis=False,
        customdata=by_source["new_customers"],
        hovertemplate="%{y}<br>Revenue $%{x:,.0f}<br>New customers %{customdata}<extra></extra>"))
    fig.update_layout(title="Revenue by traffic source", xaxis_visible=False)
    ui.bar_room(fig, by_source["revenue"])
    st.plotly_chart(ui.style(fig, legend=False), width="stretch")
with right:
    daily = now.groupby(["order_date", "traffic_source"], as_index=False)["new_customers"].sum()
    fig = go.Figure()
    for source, color in ui.color_map("traffic_source", daily["traffic_source"].unique()).items():
        part = daily[daily["traffic_source"] == source]
        if not part.empty:
            fig.add_bar(x=part["order_date"], y=part["new_customers"], name=ui.nice(source), marker_color=color,
                        hovertemplate=f"{ui.nice(source)}: %{{y}}<extra></extra>")
    fig.update_layout(title="New customers per day by source", barmode="stack", hovermode="x unified", bargap=0.15)
    st.plotly_chart(ui.style(fig), width="stretch")

st.markdown("**Campaign performance**")
campaigns = (now[now["campaign_id"] != "(none)"].groupby(["campaign_id", "traffic_source"], as_index=False)
             .agg(orders=("orders", "sum"), revenue=("revenue", "sum"), discount_cost=("discount_cost", "sum"),
                  new_customers=("new_customers", "sum"), gross_profit=("gross_profit", "sum")))
campaigns["aov"] = campaigns["revenue"] / campaigns["orders"]
campaigns["traffic_source"] = campaigns["traffic_source"].map(ui.nice)
st.dataframe(campaigns.sort_values("revenue", ascending=False), hide_index=True, width="stretch",
             column_config={
                 "campaign_id": "Campaign", "traffic_source": "Source", "orders": "Orders",
                 "revenue": st.column_config.ProgressColumn("Revenue", format="$%.0f",
                                                            max_value=float(campaigns["revenue"].max() or 1)),
                 "discount_cost": st.column_config.NumberColumn("Discount cost", format="$%.0f"),
                 "new_customers": "New customers",
                 "gross_profit": st.column_config.NumberColumn("Gross profit", format="$%.0f"),
                 "aov": st.column_config.NumberColumn("Avg order", format="$%.2f")})

left, right = st.columns([3, 2])
with left:
    cohorts = load("mart_customer_cohorts")
    if not cohorts.empty:
        grid = cohorts.pivot_table(index="cohort_week", columns="weeks_since_first", values="retention_pct")
        labels = [f"{d:%d %b}" for d in grid.index]
        sizes = cohorts.groupby("cohort_week")["cohort_size"].max().reindex(grid.index)
        fig = go.Figure(go.Heatmap(
            z=grid.values * 100, x=[f"Week {int(c)}" for c in grid.columns], y=labels, zmin=0, zmax=100,
            colorscale=[[i / 6, c] for i, c in enumerate(ui.SEQUENTIAL)], xgap=2, ygap=2,
            text=[[f"{v:.0f}%" if v == v else "" for v in row] for row in grid.values * 100],
            texttemplate="%{text}", customdata=[[s] * grid.shape[1] for s in sizes],
            colorbar=dict(ticksuffix="%", thickness=10),
            hovertemplate="Cohort %{y} · %{x}<br>%{z:.1f}% active of %{customdata} customers<extra></extra>"))
        fig.update_layout(title="Weekly cohort retention (customers acquired in the window)",
                          yaxis_autorange="reversed")
        st.plotly_chart(ui.style(fig, height=360, legend=False), width="stretch")
with right:
    rfm = load("mart_customer_rfm")
    order = ["Champions", "Loyal", "New & Promising", "Needs Attention", "At Risk", "Hibernating"]
    counts = rfm["segment"].value_counts().reindex(order).fillna(0)
    value = rfm.groupby("segment")["monetary"].sum().reindex(order).fillna(0)
    fig = go.Figure(go.Bar(
        x=counts.values, y=counts.index, orientation="h", marker_color=ui.SERIES[0],
        text=[f"{int(v):,}" for v in counts.values], textposition="outside", cliponaxis=False,
        customdata=value.values, hovertemplate="%{y}: %{x:,} customers<br>$%{customdata:,.0f} spend<extra></extra>"))
    fig.update_layout(title="RFM customer segments", xaxis_visible=False, yaxis_autorange="reversed")
    ui.bar_room(fig, counts.values)
    st.plotly_chart(ui.style(fig, height=360, legend=False), width="stretch")
