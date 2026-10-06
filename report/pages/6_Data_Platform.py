import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ui
from data import load

ui.page("Data platform", "Engineering report",
        "Health of the lakehouse itself: table freshness per medallion layer, data-quality gate results, "
        "quarantined records and streaming throughput.")

stats = load("mart_table_stats")
dq = load("dq_check_results")
quarantine = load("mart_quarantine_summary")
bronze_rows = stats.loc[stats["layer"] == "bronze", "row_count"].sum()
latest_run = dq[dq["checked_at"] == dq["checked_at"].max()] if not dq.empty else dq

c = st.columns(5)
c[0].metric("Delta tables tracked", ui.number(len(stats)), border=True)
c[1].metric("Bronze records", ui.number(bronze_rows), border=True)
c[2].metric("Quarantine rate", ui.pct(quarantine["records"].sum() / bronze_rows if bronze_rows else None, 2),
            help=f'{int(quarantine["records"].sum()):,} Bronze records rejected by Silver validation', border=True)
c[3].metric("DQ checks passed", f"{int(latest_run['passed'].sum())} / {len(latest_run)}", border=True)
c[4].metric("Pipeline runs checked", ui.number(dq["run_id"].nunique() if not dq.empty else 0), border=True)

LINEAGE = """
digraph {
  rankdir=TB; nodesep=0.25; ranksep=0.3; bgcolor="transparent"; node [shape=box style="rounded,filled" fontname="Segoe UI" fontsize=11
  color="#c3c2b7" fillcolor="#fcfcfb" fontcolor="#0b0b0b"]; edge [color="#898781" fontname="Segoe UI" fontsize=9];
  gen [label="Event generator\\norders · order_events · customers"];
  kafka [label="Kafka\\n3 topics × 3 partitions" fillcolor="#e8f0fb"];
  bronze [label="Bronze (Delta)\\nraw payload + offsets\\nSpark Structured Streaming" fillcolor="#f6e7da"];
  silver [label="Silver (Delta)\\nvalidated · deduped · MERGE\\ncustomers SCD2" fillcolor="#eef0f2"];
  q [label="Quarantine\\nrejected records + reason" fillcolor="#fbe3e3"];
  dqg [label="Data-quality gate" shape=diamond fillcolor="#fdf1d6"];
  gold [label="Gold (Delta)\\nstar schema + department marts" fillcolor="#fdf5d8"];
  rep [label="Department report\\n(this app)" fillcolor="#e7f5e7"];
  gen -> kafka -> bronze [label="stream"]; bronze -> silver [label="Airflow · availableNow"];
  silver -> q [style=dashed]; silver -> dqg -> gold -> rep;
}
"""

st.markdown("**Latest data-quality gate**")
if not latest_run.empty:
    view = latest_run.assign(status=latest_run.apply(
        lambda r: "✅ pass" if r["passed"] else ("❌ fail" if r["severity"] == "error" else "⚠️ warn"), axis=1))
    st.dataframe(view[["status", "check_name", "table_name", "severity", "observed_value", "threshold", "details"]],
                 hide_index=True, width="stretch", height=420,
                 column_config={"status": "Status", "check_name": "Check", "table_name": "Table",
                                "severity": "Severity", "observed_value": "Observed", "threshold": "Threshold",
                                "details": "What it guards"})
    st.caption(f"Run `{latest_run['run_id'].iloc[0]}` at {latest_run['checked_at'].iloc[0]:%Y-%m-%d %H:%M} UTC")
left, right = st.columns([2, 3])
with left:
    st.markdown("**Lineage**")
    st.graphviz_chart(LINEAGE, width="stretch")
with right:
    q = quarantine.groupby(["source_topic", "rejection_reason"], as_index=False)["records"].sum()
    q = q.sort_values("records")
    topics = {"orders": ui.SERIES[0], "order_events": ui.SERIES[1], "customers": ui.SERIES[2]}
    fig = go.Figure()
    for topic, color in topics.items():
        part = q[q["source_topic"] == topic]
        if not part.empty:
            fig.add_bar(y=[ui.nice(r) for r in part["rejection_reason"]], x=part["records"], name=topic,
                        orientation="h", marker_color=color,
                        hovertemplate=f"{topic} · %{{y}}: %{{x}} records<extra></extra>")
    fig.update_layout(title="Quarantined records by reason", barmode="stack", bargap=0.3)
    st.plotly_chart(ui.style(fig, height=420), width="stretch")

left, right = st.columns([3, 2])
with left:
    hourly = load("mart_orders_hourly").sort_values("hour")
    recent = hourly[hourly["hour"] >= hourly["hour"].max() - pd.Timedelta(hours=72)]
    fig = go.Figure(go.Bar(x=recent["hour"], y=recent["orders"], marker_color=ui.SERIES[0],
                           hovertemplate="%{x|%d %b %H:00}: %{y} orders<extra></extra>"))
    fig.update_layout(title="Orders per hour, last 72 hours (event time)", bargap=0.1)
    st.plotly_chart(ui.style(fig, legend=False), width="stretch")
with right:
    st.markdown("**Tables by layer**")
    st.dataframe(stats.sort_values(["layer", "table_name"]), hide_index=True, width="stretch", height=300,
                 column_config={"layer": "Layer", "table_name": "Table",
                                "row_count": st.column_config.NumberColumn("Rows", format="%d"),
                                "delta_version": "Delta version",
                                "last_updated": st.column_config.DatetimeColumn("Last commit (UTC)",
                                                                               format="YYYY-MM-DD HH:mm")})

ingest = load("mart_ingestion_hourly")
if not ingest.empty and ingest["avg_ingest_latency_seconds"].notna().any():
    st.markdown("**Kafka → Bronze latency**")
    latency = ingest.dropna(subset=["avg_ingest_latency_seconds"]).sort_values("hour")
    fig = go.Figure()
    for topic, color in topics.items():
        part = latency[latency["topic"] == topic]
        fig.add_scatter(x=part["hour"], y=part["avg_ingest_latency_seconds"], name=topic, mode="lines",
                        line_color=color, hovertemplate=f"{topic}: %{{y:.1f}} s<extra></extra>")
    fig.update_layout(yaxis_ticksuffix=" s", hovermode="x unified")
    st.plotly_chart(ui.style(fig, height=260), width="stretch")
