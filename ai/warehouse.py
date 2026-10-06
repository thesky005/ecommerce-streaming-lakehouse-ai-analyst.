"""Read-only SQL access to the Gold layer for the AI agent.

Gold Delta tables are loaded into an in-memory DuckDB database. The agent may only run
single SELECT statements: statement types are checked by DuckDB's own parser, external
file and network access is disabled, and results are capped, so a model-written query can
read the data but never change it or reach outside it.
"""
import os
import threading
from pathlib import Path

import duckdb
import pandas as pd
from deltalake import DeltaTable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_ROWS = 200
MAX_RESULT_CHARS = 12000

# Business meaning of each table, given to the model with the column list.
TABLE_DOCS = {
    "fact_orders": "One row per order with its full lifecycle. order_ts/order_date = when placed. Money in USD: "
                   "merchandise_amount (net of discount, excl. shipping), discount_amount, shipping_fee, order_total, "
                   "cost_amount (COGS), gross_profit, refund_amount. paid_at, shipped_at, delivered_at, cancelled_at, "
                   "return_requested_at, refunded_at are timestamps (NULL if not happened). order_status in "
                   "(pending_payment, payment_failed, processing, shipped, delivered, returned, cancelled). "
                   "hours_to_ship, days_to_deliver, is_late_delivery (delivered after promised_delivery_date), "
                   "is_overdue (not delivered and past promise), is_new_customer (first order), rating 1-5 (NULL if no "
                   "review), payment_failures (count), cancel_reason, return_reason, returned_sku, carrier, "
                   "warehouse_id, channel, traffic_source, campaign_id, payment_method, ship_region, "
                   "loyalty_tier_at_order.",
    "fact_order_items": "One row per order line. net_amount (after discount), gross_amount, discount_amount, "
                        "cost_amount, gross_profit, quantity, sku, product_name, category, brand, is_returned_line, "
                        "is_cancelled, plus order attributes (order_date, channel, traffic_source, ship_region, "
                        "warehouse_id, order_status).",
    "dim_product": "Product catalogue: sku, product_name, category, brand, unit_price, unit_cost, list_margin_pct.",
    "dim_customer": "Customer SCD Type 2 history: one row per version (valid_from/valid_to, is_current). Attributes: "
                    "city, region, loyalty_tier, marketing_opt_in, acquisition_source, signup_date, first_order_ts. "
                    "Use is_current = true for the latest state. customer_sk = '-1' is the unknown member.",
    "dim_date": "Calendar: date_key, date, year, quarter, month, month_name, week_of_year, day_name, is_weekend.",
    "mart_sales_daily": "Daily net sales by order_date, channel, ship_region, category (cancelled orders excluded).",
    "mart_product_performance": "All-time product performance: units, net_sales, gross_profit, margin_pct, "
                                "returned_units, return_rate.",
    "mart_marketing_channels": "Daily orders/revenue/discount_cost/new_customers by traffic_source and campaign_id.",
    "mart_customer_cohorts": "Weekly acquisition cohorts: cohort_week, weeks_since_first, active_customers, "
                             "cohort_size, retention_pct.",
    "mart_customer_rfm": "Per-customer RFM: recency_days, frequency, monetary, r/f/m scores, segment.",
    "mart_fulfillment_daily": "Daily fulfilment by order_date and warehouse_id: shipped, delivered, avg/p90 hours to "
                              "ship, late_deliveries, on_time_rate.",
    "mart_carrier_performance": "All-time carrier scorecard: shipments, transit days, late deliveries, on_time_rate.",
    "mart_order_backlog": "Live snapshot of open orders by warehouse_id and order_status, overdue counts, value.",
    "mart_finance_daily": "Daily finance by date: gross_sales, discounts, net_merchandise, shipping_revenue, refunds "
                          "(by refund date), cogs, net_revenue, gross_profit, gross_margin_pct, payment_failures.",
    "mart_payment_methods": "All-time payment methods: orders, failure rate, lost orders, collected amount.",
    "mart_cs_daily": "Daily customer service by event date: deliveries, returns, cancellations, reviews, avg_rating, "
                     "low_ratings, late_deliveries, return_rate.",
    "mart_return_reasons": "Returns and refund amount by return_reason and product category (all time).",
    "mart_cs_attention_queue": "Open cases needing follow-up: issue_type (delivery_overdue, low_rating, "
                               "refund_pending), priority, days_open.",
    "dq_check_results": "Data-quality gate results per pipeline run.",
}
SKIP_TABLES = {"mart_table_stats", "mart_ingestion_hourly", "mart_orders_hourly", "mart_quarantine_summary"}


class QueryError(ValueError):
    pass


class Warehouse:
    def __init__(self, lake_root: str | Path | None = None):
        self.lake_root = Path(lake_root or os.getenv("LAKE_ROOT", PROJECT_ROOT / "lake"))
        self._lock = threading.Lock()
        self.version = ""
        self.tables: dict[str, list[tuple[str, str]]] = {}
        self.row_counts: dict[str, int] = {}
        self.reload()

    def reload(self) -> None:
        gold = self.lake_root / "gold"
        if not gold.exists():
            raise FileNotFoundError(f"No Gold layer at {gold}. Run scripts/run_local.py first.")
        con = duckdb.connect(":memory:", config={"TimeZone": "UTC"})
        versions, tables, counts = [], {}, {}
        for path in sorted(p for p in gold.iterdir() if (p / "_delta_log").exists()):
            if path.name in SKIP_TABLES:
                continue
            table = DeltaTable(str(path))
            frame = table.to_pandas()
            for column in frame.columns:  # Delta dates arrive as objects; give DuckDB real DATE columns
                if frame[column].dtype == object and (column == "date" or column.endswith("_date")):
                    frame[column] = pd.to_datetime(frame[column]).dt.date
            con.register("_frame", frame)
            con.execute(f'CREATE TABLE "{path.name}" AS SELECT * FROM _frame')
            con.unregister("_frame")
            tables[path.name] = [(r[0], r[1]) for r in con.execute(f'DESCRIBE "{path.name}"').fetchall()]
            counts[path.name] = len(frame)
            versions.append(f"{path.name}:{table.version()}")
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
        with self._lock:
            self.con, self.tables, self.row_counts = con, tables, counts
            self.version = "|".join(versions)

    # -------------------------------------------------------------- schema
    def schema_text(self) -> str:
        lines = []
        for name, columns in self.tables.items():
            cols = ", ".join(f"{c} {t.lower()}" for c, t in columns)
            doc = TABLE_DOCS.get(name, "")
            lines.append(f"- {name} ({self.row_counts[name]:,} rows): {doc}\n  columns: {cols}")
        return "\n".join(lines)

    def describe(self, table: str) -> str:
        if table not in self.tables:
            return f"Unknown table '{table}'. Tables: {', '.join(self.tables)}"
        sample = self.query(f'SELECT * FROM "{table}" LIMIT 3')
        cols = "\n".join(f"  {c}: {t}" for c, t in self.tables[table])
        return f"{table}: {TABLE_DOCS.get(table, '')}\nColumns:\n{cols}\nSample rows:\n{sample['text']}"

    # -------------------------------------------------------------- queries
    def _validate(self, sql: str) -> str:
        sql = sql.strip().rstrip(";").strip()
        if not sql:
            raise QueryError("Empty query.")
        try:
            statements = self.con.extract_statements(sql)
        except duckdb.Error as error:
            raise QueryError(f"SQL syntax error: {error}") from error
        if len(statements) != 1:
            raise QueryError("Send exactly one SELECT statement per call.")
        if statements[0].type != duckdb.StatementType.SELECT:
            raise QueryError("Only read-only SELECT queries are allowed.")
        return sql

    def query(self, sql: str) -> dict:
        sql = self._validate(sql)
        with self._lock:
            cursor = self.con.cursor()
        try:
            result = cursor.execute(f"SELECT * FROM ({sql}) AS q LIMIT {MAX_ROWS + 1}")
            columns = [d[0] for d in result.description]
            rows = result.fetchall()
        except duckdb.Error as error:
            raise QueryError(str(error).split("\n")[0]) from error
        finally:
            cursor.close()
        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]
        return {"columns": columns, "rows": rows, "truncated": truncated, "text": _format(columns, rows, truncated)}


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}" if abs(value) < 1 else f"{value:,.2f}"
    return str(value)


def _format(columns: list[str], rows: list[tuple], truncated: bool) -> str:
    lines = [" | ".join(columns)] + [" | ".join(_cell(v) for v in row) for row in rows]
    text = "\n".join(lines)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + "\n… (output truncated; aggregate further)"
    if truncated:
        text += f"\n… (only the first {MAX_ROWS} rows shown; aggregate or filter further)"
    return text or "(no rows)"
