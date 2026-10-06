import plotly.graph_objects as go
import streamlit as st

import ui
from data import load

ui.page("Operations", "Department report",
        "How fast warehouses ship, how reliably carriers deliver, and what is still open right now.")
window = ui.date_filter()

fulfilment = load("mart_fulfillment_daily")
with st.sidebar:
    warehouses = st.multiselect("Warehouse", sorted(fulfilment["warehouse_id"].unique()))
now = ui.in_range(fulfilment, "order_date", window)
orders = ui.in_range(load("fact_orders"), "order_date", window)
orders = orders[orders["order_status"] != "cancelled"]
if warehouses:
    now = now[now["warehouse_id"].isin(warehouses)]
    orders = orders[orders["warehouse_id"].isin(warehouses)]

backlog = load("mart_order_backlog")
if warehouses:
    backlog = backlog[backlog["warehouse_id"].isin(warehouses)]
delivered = orders[orders["delivered_at"].notna()]

c = st.columns(5)
c[0].metric("Avg hours to ship", f"{orders['hours_to_ship'].mean():.1f} h", border=True)
c[1].metric("90th pct hours to ship", f"{orders['hours_to_ship'].quantile(0.9):.1f} h", border=True)
c[2].metric("Avg days to deliver", f"{delivered['days_to_deliver'].mean():.1f} d", border=True)
c[3].metric("On-time delivery", ui.pct(1 - delivered["is_late_delivery"].mean() if len(delivered) else None),
            border=True)
c[4].metric("Open orders (overdue)", f"{int(backlog['open_orders'].sum()):,} ({int(backlog['overdue_orders'].sum())})",
            border=True)

left, right = st.columns([3, 2])
with left:
    speed = (orders.dropna(subset=["hours_to_ship"]).groupby(["order_date", "warehouse_id"], as_index=False)
             ["hours_to_ship"].mean())
    fig = go.Figure()
    for warehouse, color in ui.color_map("warehouse_id", speed["warehouse_id"].unique()).items():
        part = speed[speed["warehouse_id"] == warehouse]
        if not part.empty:
            fig.add_scatter(x=part["order_date"], y=part["hours_to_ship"], name=warehouse, mode="lines",
                            line_color=color, hovertemplate=f"{warehouse}: %{{y:.1f}} h<extra></extra>")
    fig.update_layout(title="Average hours from order to shipment", yaxis_ticksuffix=" h", hovermode="x unified")
    st.plotly_chart(ui.style(fig), width="stretch")
with right:
    carriers = (delivered.groupby("carrier", as_index=False)
                .agg(on_time=("is_late_delivery", lambda s: 1 - s.mean()), deliveries=("order_id", "count")))
    carriers = carriers.sort_values("on_time")
    fig = go.Figure(go.Bar(
        x=carriers["on_time"] * 100, y=carriers["carrier"], orientation="h",
        marker_color=[ui.COLORS["carrier"].get(v) for v in carriers["carrier"]],
        text=[f"{v * 100:.1f}%" for v in carriers["on_time"]], textposition="outside", cliponaxis=False,
        customdata=carriers["deliveries"],
        hovertemplate="%{y}: %{x:.1f}% on time<br>%{customdata:,} deliveries<extra></extra>"))
    fig.update_layout(title="On-time delivery rate by carrier", xaxis=dict(range=[0, 110], visible=False))
    st.plotly_chart(ui.style(fig, legend=False), width="stretch")

left, right = st.columns(2)
with left:
    st.markdown("**Open order backlog (live snapshot)**")
    view = backlog.copy()
    view["order_status"] = view["order_status"].map(ui.nice)
    st.dataframe(view.sort_values(["warehouse_id", "order_status"])[
        ["warehouse_id", "order_status", "open_orders", "overdue_orders", "oldest_order_hours", "open_value"]],
        hide_index=True, width="stretch",
        column_config={"warehouse_id": "Warehouse", "order_status": "Status", "open_orders": "Open",
                       "overdue_orders": "Overdue",
                       "oldest_order_hours": st.column_config.NumberColumn("Oldest (h)", format="%.0f"),
                       "open_value": st.column_config.NumberColumn("Value", format="$%.0f")})
with right:
    st.markdown("**Carrier scorecard (all time)**")
    st.dataframe(load("mart_carrier_performance"), hide_index=True, width="stretch",
                 column_config={"carrier": "Carrier", "shipments": "Shipments", "delivered": "Delivered",
                                "avg_transit_days": st.column_config.NumberColumn("Transit (days)", format="%.1f"),
                                "late_deliveries": "Late", "damaged_returns": "Damaged returns",
                                "avg_rating": st.column_config.NumberColumn("Avg rating", format="%.2f ⭐"),
                                "on_time_rate": st.column_config.NumberColumn("On time", format="percent")})

volume = now.groupby("warehouse_id", as_index=False)[["orders", "shipped", "delivered", "late_deliveries"]].sum()
st.markdown("**Warehouse throughput in the period**")
st.dataframe(volume, hide_index=True, width="stretch",
             column_config={"warehouse_id": "Warehouse", "orders": "Orders", "shipped": "Shipped",
                            "delivered": "Delivered", "late_deliveries": "Late deliveries"})
