import plotly.graph_objects as go
import streamlit as st

import ui
from data import load

ui.page("Customer service", "Department report",
        "Returns, cancellations and ratings, plus the queue of orders that need a person to look at them.")
window = ui.date_filter()
before = ui.previous_window(window)

cs = load("mart_cs_daily")
now, prev = ui.in_range(cs, "date", window), ui.in_range(cs, "date", before)
t, p = now.sum(numeric_only=True), prev.sum(numeric_only=True)
queue = load("mart_cs_attention_queue")

reviews = ui.in_range(load("fact_orders"), "order_date", window)["rating"].dropna()
c = st.columns(5)
c[0].metric("Return rate", ui.pct(t["returns"] / t["deliveries"] if t["deliveries"] else None), border=True)
c[1].metric("Returns", ui.number(t["returns"]), ui.delta(t["returns"], p["returns"]), delta_color="inverse",
            border=True)
c[2].metric("Cancellations", ui.number(t["cancellations"]), ui.delta(t["cancellations"], p["cancellations"]),
            delta_color="inverse", border=True)
c[3].metric("Average rating", f"{reviews.mean():.2f} ⭐" if len(reviews) else "–", border=True)
c[4].metric("High-priority cases", ui.number((queue["priority"] == "high").sum()), border=True)

left, right = st.columns([3, 2])
with left:
    daily = now.sort_values("date")
    fig = go.Figure()
    for column, name, color in (("returns", "Returns", ui.SERIES[0]), ("cancellations", "Cancellations", ui.SERIES[1]),
                                ("late_deliveries", "Late deliveries", ui.SERIES[2])):
        fig.add_scatter(x=daily["date"], y=daily[column], name=name, mode="lines", line_color=color,
                        hovertemplate=f"{name}: %{{y}}<extra></extra>")
    fig.update_layout(title="Daily service workload drivers", hovermode="x unified")
    st.plotly_chart(ui.style(fig), width="stretch")
with right:
    distribution = reviews.astype(int).value_counts().reindex([5, 4, 3, 2, 1]).fillna(0)
    fig = go.Figure(go.Bar(
        x=distribution.values, y=[f"{s} ⭐" for s in distribution.index], orientation="h",
        marker_color=[ui.SERIES[0]] * 3 + [ui.SERIES[7]] * 2,
        text=[f"{int(v):,}" for v in distribution.values], textposition="outside", cliponaxis=False,
        hovertemplate="%{y}: %{x:,} reviews<extra></extra>"))
    fig.update_layout(title="Rating distribution (orders in the period)", xaxis_visible=False,
                      yaxis_autorange="reversed")
    ui.bar_room(fig, distribution.values)
    st.plotly_chart(ui.style(fig, legend=False), width="stretch")

left, right = st.columns([2, 3])
with left:
    reasons = load("mart_return_reasons")
    pivot = reasons.pivot_table(index="return_reason", columns="category", values="returns", aggfunc="sum").fillna(0)
    pivot = pivot.loc[pivot.sum(axis=1).sort_values().index]
    fig = go.Figure()
    for category, color in ui.color_map("category", pivot.columns).items():
        if category in pivot:
            fig.add_bar(y=[ui.nice(r) for r in pivot.index], x=pivot[category], name=category, orientation="h",
                        marker_color=color, hovertemplate=f"{category}: %{{x}} returns<extra></extra>")
    fig.update_layout(title="Return reasons by category (all time)", barmode="stack", bargap=0.3)
    st.plotly_chart(ui.style(fig, height=380), width="stretch")
with right:
    st.markdown("**Attention queue**")
    issue = st.segmented_control("Issue", ["delivery_overdue", "low_rating", "refund_pending"],
                                 format_func=ui.nice, selection_mode="multi", default=None,
                                 label_visibility="collapsed")
    view = queue[queue["issue_type"].isin(issue)] if issue else queue
    view = view.sort_values(["priority", "days_open"], ascending=[True, False])
    view = view.assign(issue_type=view["issue_type"].map(ui.nice), order_status=view["order_status"].map(ui.nice))
    st.dataframe(view, hide_index=True, width="stretch", height=330,
                 column_config={"order_id": "Order", "customer_id": "Customer",
                                "order_date": st.column_config.DateColumn("Ordered"), "issue_type": "Issue",
                                "priority": "Priority", "days_open": "Days open", "order_status": "Status",
                                "warehouse_id": "Warehouse", "carrier": "Carrier", "rating": "Rating",
                                "return_reason": "Return reason",
                                "order_total": st.column_config.NumberColumn("Value", format="$%.2f")})
