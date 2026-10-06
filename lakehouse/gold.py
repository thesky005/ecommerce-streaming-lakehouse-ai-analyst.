"""Gold: dimensional model and department marts.

* Dimensions: dim_date, dim_product, dim_customer (SCD2 versions + an "unknown" member).
* Facts: fact_orders (one row per order, lifecycle milestones pivoted from events) and
  fact_order_items (one row per order line, priced and costed). Orders are joined to the
  customer version that was valid at order time (point-in-time join).
* Marts: one group of aggregate tables per department, read by the report.

Gold tables are rebuilt from Silver on each run (full refresh), which keeps them
deterministic and idempotent.
"""
from delta.tables import DeltaTable
from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from lakehouse import config

UNKNOWN_CUSTOMER_SK = "-1"


def _silver(spark: SparkSession, name: str) -> DataFrame:
    return spark.read.format("delta").load(config.silver(name))


def _gold(spark: SparkSession, name: str) -> DataFrame:
    return spark.read.format("delta").load(config.gold(name))


def _write(df: DataFrame, name: str) -> None:
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(config.gold(name))
    print(f"gold.{name}: {df.sparkSession.read.format('delta').load(config.gold(name)).count()} rows")


def _hours_between(start: str, end: str) -> Column:
    return F.round((F.unix_timestamp(end) - F.unix_timestamp(start)) / 3600, 1)


def _safe_div(numerator: Column, denominator: Column) -> Column:
    return F.when(denominator > 0, F.round(numerator / denominator, 4))


# ------------------------------------------------------------------ dimensions
def build_dimensions(spark: SparkSession) -> None:
    orders = _silver(spark, "orders")
    start, end = orders.agg(F.min("order_date"), F.max("promised_delivery_date")).first()
    dim_date = spark.sql(
        f"SELECT explode(sequence(to_date('{start}'), date_add(to_date('{end}'), 30), interval 1 day)) AS date"
    ).select(
        F.date_format("date", "yyyyMMdd").cast("int").alias("date_key"),
        "date",
        F.year("date").alias("year"),
        F.quarter("date").alias("quarter"),
        F.month("date").alias("month"),
        F.date_format("date", "MMMM").alias("month_name"),
        F.weekofyear("date").alias("week_of_year"),
        F.date_format("date", "EEEE").alias("day_name"),
        F.dayofweek("date").isin(1, 7).alias("is_weekend"),
    )
    _write(dim_date, "dim_date")

    dim_product = _silver(spark, "products").select(
        "sku", "product_name", "category", "brand", "unit_price", "unit_cost",
        F.round((F.col("unit_price") - F.col("unit_cost")) / F.col("unit_price"), 3).alias("list_margin_pct"),
    )
    _write(dim_product, "dim_product")

    first_orders = orders.groupBy("customer_id").agg(F.min("order_ts").alias("first_order_ts"))
    customers = _silver(spark, "customers").join(first_orders, "customer_id", "left").select(
        "customer_sk", "customer_id", "city", "region", "country", "loyalty_tier", "marketing_opt_in",
        "acquisition_source", "signup_date", "valid_from", "valid_to", "is_current", "first_order_ts",
    )
    unknown = spark.range(1).select(
        F.lit(UNKNOWN_CUSTOMER_SK).alias("customer_sk"), F.lit("UNKNOWN").alias("customer_id"),
        F.lit(True).alias("is_current"),
    )
    _write(customers.unionByName(unknown, allowMissingColumns=True), "dim_customer")


# ------------------------------------------------------------------------ facts
def _lifecycle(events: DataFrame) -> DataFrame:
    def first(event_type: str) -> Column:
        return F.min(F.when(F.col("event_type") == event_type, F.col("event_ts")))

    def value(event_type: str, column: str) -> Column:
        return F.max(F.when(F.col("event_type") == event_type, F.col(column)))

    return events.groupBy("order_id").agg(
        first("payment_captured").alias("paid_at"),
        F.count(F.when(F.col("event_type") == "payment_failed", 1)).alias("payment_failures"),
        first("order_cancelled").alias("cancelled_at"),
        value("order_cancelled", "reason").alias("cancel_reason"),
        first("order_shipped").alias("shipped_at"),
        value("order_shipped", "carrier").alias("carrier"),
        first("order_delivered").alias("delivered_at"),
        first("return_requested").alias("return_requested_at"),
        value("return_requested", "reason").alias("return_reason"),
        value("return_requested", "sku").alias("returned_sku"),
        F.coalesce(F.sum(F.when(F.col("event_type") == "refund_issued", F.col("amount"))), F.lit(0.0))
        .alias("refund_amount"),
        first("refund_issued").alias("refunded_at"),
        value("review_submitted", "rating").alias("rating"),
    )


def build_facts(spark: SparkSession) -> None:
    orders = _silver(spark, "orders")
    items = _silver(spark, "order_items")
    products = _gold(spark, "dim_product")
    customers = _gold(spark, "dim_customer").where(F.col("customer_id") != "UNKNOWN")

    costed = items.join(products.select("sku", "product_name", "category", "brand", "unit_cost"), "sku", "left") \
        .withColumn("gross_amount", F.round(F.col("unit_price") * F.col("quantity"), 2)) \
        .withColumn("cost_amount", F.round(F.col("unit_cost") * F.col("quantity"), 2))
    totals = costed.groupBy("order_id").agg(
        F.round(F.sum("gross_amount"), 2).alias("gross_amount"),
        F.round(F.sum("discount_amount"), 2).alias("discount_amount"),
        F.round(F.sum("cost_amount"), 2).alias("cost_amount"),
    )

    c = customers.alias("c")
    point_in_time = orders.alias("o").join(
        c,
        (F.col("o.customer_id") == F.col("c.customer_id"))
        & (F.col("o.order_ts") >= F.col("c.valid_from"))
        & (F.col("c.valid_to").isNull() | (F.col("o.order_ts") < F.col("c.valid_to"))),
        "left",
    ).select(
        "o.*",
        F.coalesce(F.col("c.customer_sk"), F.lit(UNKNOWN_CUSTOMER_SK)).alias("customer_sk"),
        F.col("c.loyalty_tier").alias("loyalty_tier_at_order"),
        F.col("c.signup_date").alias("signup_date"),
    )

    by_customer = Window.partitionBy("customer_id").orderBy("order_ts")
    status = (
        F.when(F.col("cancelled_at").isNotNull(), "cancelled")
        .when(F.col("return_requested_at").isNotNull(), "returned")
        .when(F.col("delivered_at").isNotNull(), "delivered")
        .when(F.col("shipped_at").isNotNull(), "shipped")
        .when(F.col("paid_at").isNotNull(), "processing")
        .when(F.col("payment_failures") > 0, "payment_failed")
        .otherwise("pending_payment")
    )
    fact_orders = (
        point_in_time.join(totals, "order_id", "left")
        .join(_lifecycle(_silver(spark, "order_events")), "order_id", "left")
        .withColumn("payment_failures", F.coalesce("payment_failures", F.lit(0)))
        .withColumn("refund_amount", F.coalesce("refund_amount", F.lit(0.0)))
        .withColumn("date_key", F.date_format("order_date", "yyyyMMdd").cast("int"))
        .withColumn("order_total", F.round(F.col("merchandise_amount") + F.col("shipping_fee"), 2))
        .withColumn("gross_profit", F.round(F.col("merchandise_amount") - F.col("cost_amount"), 2))
        .withColumn("is_new_customer", F.coalesce((F.row_number().over(by_customer) == 1)
                    & (F.col("signup_date") >= F.date_sub("order_date", 1)), F.lit(False)))
        .withColumn("order_status", status)
        .withColumn("hours_to_ship", _hours_between("order_ts", "shipped_at"))
        .withColumn("days_to_deliver", F.round(_hours_between("order_ts", "delivered_at") / 24, 2))
        .withColumn("is_late_delivery", F.to_date("delivered_at") > F.col("promised_delivery_date"))
        .withColumn("is_overdue", F.col("delivered_at").isNull() & F.col("cancelled_at").isNull()
                    & (F.current_date() > F.col("promised_delivery_date")))
        .drop("event_id", "ingested_at", "processed_at")
    )
    _write(fact_orders, "fact_orders")

    order_attributes = _gold(spark, "fact_orders").select(
        "order_id", "order_ts", "date_key", "customer_id", "customer_sk", "channel", "traffic_source",
        "campaign_id", "ship_region", "warehouse_id", "order_status", "returned_sku", "paid_at",
    )
    fact_items = costed.join(order_attributes, "order_id").select(
        "order_id", "line_id", "order_ts", "order_date", "date_key", "customer_id", "customer_sk",
        "sku", "product_name", "category", "brand", "quantity", "unit_price", "gross_amount",
        "discount_amount", "net_amount", "cost_amount",
        F.round(F.col("net_amount") - F.col("cost_amount"), 2).alias("gross_profit"),
        "channel", "traffic_source", "campaign_id", "ship_region", "warehouse_id", "order_status",
        (F.col("returned_sku") == F.col("sku")).alias("is_returned_line"),
        (F.col("order_status") == "cancelled").alias("is_cancelled"),
    )
    _write(fact_items, "fact_order_items")


# ------------------------------------------------------------------------ marts
def build_sales(spark: SparkSession) -> None:
    items = _gold(spark, "fact_order_items")
    active = items.where(~F.col("is_cancelled"))
    _write(active.groupBy("order_date", "channel", "ship_region", "category").agg(
        F.countDistinct("order_id").alias("orders"),
        F.sum("quantity").alias("units"),
        F.round(F.sum("gross_amount"), 2).alias("gross_sales"),
        F.round(F.sum("discount_amount"), 2).alias("discounts"),
        F.round(F.sum("net_amount"), 2).alias("net_sales"),
        F.round(F.sum("gross_profit"), 2).alias("gross_profit"),
    ), "mart_sales_daily")

    _write(active.groupBy("sku", "product_name", "category", "brand").agg(
        F.countDistinct("order_id").alias("orders"),
        F.sum("quantity").alias("units"),
        F.round(F.sum("net_amount"), 2).alias("net_sales"),
        F.round(F.sum("gross_profit"), 2).alias("gross_profit"),
        F.sum(F.when(F.col("is_returned_line"), F.col("quantity")).otherwise(0)).alias("returned_units"),
    ).withColumn("margin_pct", _safe_div(F.col("gross_profit"), F.col("net_sales")))
     .withColumn("return_rate", _safe_div(F.col("returned_units"), F.col("units"))), "mart_product_performance")


def build_marketing(spark: SparkSession) -> None:
    orders = _gold(spark, "fact_orders").where(F.col("order_status") != "cancelled")
    _write(orders.groupBy(
        "order_date", "traffic_source", F.coalesce("campaign_id", F.lit("(none)")).alias("campaign_id")
    ).agg(
        F.count("*").alias("orders"),
        F.round(F.sum("merchandise_amount"), 2).alias("revenue"),
        F.round(F.sum("discount_amount"), 2).alias("discount_cost"),
        F.round(F.sum("gross_profit"), 2).alias("gross_profit"),
        F.sum(F.col("is_new_customer").cast("int")).alias("new_customers"),
    ).withColumn("returning_orders", F.col("orders") - F.col("new_customers")), "mart_marketing_channels")

    # Weekly acquisition cohorts: customers whose first-ever order falls inside the data window.
    cohort = orders.where("is_new_customer").select(
        "customer_id", F.date_trunc("week", "order_ts").cast("date").alias("cohort_week"))
    activity = orders.join(cohort, "customer_id").withColumn(
        "weeks_since_first", F.floor(F.datediff(F.date_trunc("week", "order_ts").cast("date"), "cohort_week") / 7))
    sizes = cohort.groupBy("cohort_week").agg(F.countDistinct("customer_id").alias("cohort_size"))
    _write(activity.groupBy("cohort_week", "weeks_since_first").agg(
        F.countDistinct("customer_id").alias("active_customers"),
        F.round(F.sum("merchandise_amount"), 2).alias("revenue"),
    ).join(sizes, "cohort_week").withColumn(
        "retention_pct", F.round(F.col("active_customers") / F.col("cohort_size"), 4)), "mart_customer_cohorts")

    # RFM segmentation on the observed window.
    as_of = orders.agg(F.max("order_ts")).first()[0]
    rfm = orders.groupBy("customer_id").agg(
        F.datediff(F.lit(as_of), F.max("order_ts")).alias("recency_days"),
        F.count("*").alias("frequency"),
        F.round(F.sum("merchandise_amount"), 2).alias("monetary"),
    )
    def score(order: Column) -> Column:
        # percent_rank gives tied values the same score (ntile would split ties arbitrarily,
        # which matters because most customers have exactly one order in the window).
        return F.least(F.lit(5), F.floor(F.percent_rank().over(Window.orderBy(order)) * 5) + 1).cast("int")

    rfm = (rfm.withColumn("r_score", score(F.desc("recency_days")))
              .withColumn("f_score", score(F.col("frequency")))
              .withColumn("m_score", score(F.col("monetary"))))
    segment = (
        F.when((F.col("r_score") >= 4) & (F.col("f_score") >= 4), "Champions")
        .when((F.col("r_score") >= 3) & (F.col("f_score") >= 3), "Loyal")
        .when((F.col("r_score") >= 4) & (F.col("f_score") <= 2), "New & Promising")
        .when((F.col("r_score") <= 2) & (F.col("f_score") >= 3), "At Risk")
        .when((F.col("r_score") <= 2) & (F.col("f_score") <= 2), "Hibernating")
        .otherwise("Needs Attention")
    )
    current = _gold(spark, "dim_customer").where("is_current").select("customer_id", "loyalty_tier", "region")
    _write(rfm.withColumn("segment", segment).join(current, "customer_id", "left"), "mart_customer_rfm")


def build_operations(spark: SparkSession) -> None:
    orders = _gold(spark, "fact_orders").where(F.col("order_status") != "cancelled")
    delivered = F.col("delivered_at").isNotNull()
    _write(orders.groupBy("order_date", "warehouse_id").agg(
        F.count("*").alias("orders"),
        F.count("shipped_at").alias("shipped"),
        F.count("delivered_at").alias("delivered"),
        F.round(F.avg("hours_to_ship"), 1).alias("avg_hours_to_ship"),
        F.round(F.percentile_approx("hours_to_ship", 0.9), 1).alias("p90_hours_to_ship"),
        F.round(F.avg("days_to_deliver"), 2).alias("avg_days_to_deliver"),
        F.sum(F.col("is_late_delivery").cast("int")).alias("late_deliveries"),
    ).withColumn("on_time_rate", _safe_div(F.col("delivered") - F.col("late_deliveries"), F.col("delivered"))),
        "mart_fulfillment_daily")

    shipped = orders.where(F.col("carrier").isNotNull())
    _write(shipped.groupBy("carrier").agg(
        F.count("*").alias("shipments"),
        F.count("delivered_at").alias("delivered"),
        F.round(F.avg(F.when(delivered, _hours_between("shipped_at", "delivered_at") / 24)), 2).alias("avg_transit_days"),
        F.sum(F.col("is_late_delivery").cast("int")).alias("late_deliveries"),
        F.count(F.when(F.col("return_reason") == "arrived_damaged", 1)).alias("damaged_returns"),
        F.round(F.avg("rating"), 2).alias("avg_rating"),
    ).withColumn("on_time_rate", _safe_div(F.col("delivered") - F.col("late_deliveries"), F.col("delivered"))),
        "mart_carrier_performance")

    open_orders = orders.where(F.col("order_status").isin("pending_payment", "payment_failed", "processing", "shipped"))
    _write(open_orders.groupBy("warehouse_id", "order_status").agg(
        F.count("*").alias("open_orders"),
        F.sum(F.col("is_overdue").cast("int")).alias("overdue_orders"),
        F.round(F.max((F.unix_timestamp(F.current_timestamp()) - F.unix_timestamp("order_ts")) / 3600), 1)
        .alias("oldest_order_hours"),
        F.round(F.sum("order_total"), 2).alias("open_value"),
    ).withColumn("snapshot_at", F.current_timestamp()), "mart_order_backlog")


def build_finance(spark: SparkSession) -> None:
    orders = _gold(spark, "fact_orders")
    events = _silver(spark, "order_events")
    paid = F.col("paid_at").isNotNull()
    kept = paid & (F.col("order_status") != "cancelled")

    bookings = orders.groupBy(F.col("order_date").alias("date")).agg(
        F.count("*").alias("orders"),
        F.count(F.when(paid, 1)).alias("paid_orders"),
        F.round(F.sum(F.when(paid, F.col("gross_amount"))), 2).alias("gross_sales"),
        F.round(F.sum(F.when(paid, F.col("discount_amount"))), 2).alias("discounts"),
        F.round(F.sum(F.when(paid, F.col("merchandise_amount"))), 2).alias("net_merchandise"),
        F.round(F.sum(F.when(paid, F.col("shipping_fee"))), 2).alias("shipping_revenue"),
        F.round(F.sum(F.when(kept, F.col("cost_amount"))), 2).alias("cogs"),
    )
    refunds = events.where("event_type = 'refund_issued'").groupBy(F.col("event_date").alias("date")).agg(
        F.round(F.sum("amount"), 2).alias("refunds"), F.count("*").alias("refund_count"))
    failures = events.where("event_type = 'payment_failed'").groupBy(F.col("event_date").alias("date")).agg(
        F.count("*").alias("payment_failures"))
    daily = (bookings.join(refunds, "date", "full").join(failures, "date", "full").na.fill(0)
             .withColumn("net_revenue", F.round(F.col("net_merchandise") + F.col("shipping_revenue") - F.col("refunds"), 2))
             .withColumn("gross_profit", F.round(F.col("net_revenue") - F.col("cogs"), 2))
             .withColumn("gross_margin_pct", _safe_div(F.col("gross_profit"), F.col("net_revenue"))))
    _write(daily, "mart_finance_daily")

    _write(orders.groupBy("payment_method").agg(
        F.count("*").alias("orders"),
        F.count(F.when(F.col("payment_failures") > 0, 1)).alias("orders_with_failure"),
        F.sum("payment_failures").alias("failed_attempts"),
        F.count(F.when(F.col("cancel_reason") == "payment_failed", 1)).alias("lost_orders"),
        F.round(F.sum(F.when(paid, F.col("order_total"))), 2).alias("collected_amount"),
        F.round(F.avg(F.when(paid, F.col("order_total"))), 2).alias("avg_order_value"),
    ).withColumn("failure_rate", _safe_div(F.col("orders_with_failure"), F.col("orders"))), "mart_payment_methods")


def build_customer_service(spark: SparkSession) -> None:
    events = _silver(spark, "order_events")
    orders = _gold(spark, "fact_orders")

    def count_of(event_type: str) -> Column:
        return F.count(F.when(F.col("event_type") == event_type, 1))

    daily = events.groupBy(F.col("event_date").alias("date")).agg(
        count_of("order_delivered").alias("deliveries"),
        count_of("return_requested").alias("returns"),
        count_of("order_cancelled").alias("cancellations"),
        count_of("review_submitted").alias("reviews"),
        F.round(F.avg(F.when(F.col("event_type") == "review_submitted", F.col("rating"))), 2).alias("avg_rating"),
        F.count(F.when((F.col("event_type") == "review_submitted") & (F.col("rating") <= 2), 1)).alias("low_ratings"),
    )
    late = orders.where("delivered_at IS NOT NULL").groupBy(F.to_date("delivered_at").alias("date")).agg(
        F.sum(F.col("is_late_delivery").cast("int")).alias("late_deliveries"))
    _write(daily.join(late, "date", "left").na.fill(0, ["late_deliveries"])
           .withColumn("return_rate", _safe_div(F.col("returns"), F.col("deliveries"))), "mart_cs_daily")

    products = _gold(spark, "dim_product").select(F.col("sku").alias("returned_sku"), "category")
    _write(orders.where("return_requested_at IS NOT NULL").join(products, "returned_sku", "left")
           .groupBy("return_reason", "category").agg(
               F.count("*").alias("returns"), F.round(F.sum("refund_amount"), 2).alias("refund_amount")),
           "mart_return_reasons")

    issue = (
        F.when(F.col("is_overdue"), "delivery_overdue")
        .when(F.col("rating") <= 2, "low_rating")
        .when(F.col("return_requested_at").isNotNull() & F.col("refunded_at").isNull(), "refund_pending")
    )
    queue = (orders.withColumn("issue_type", issue).where(F.col("issue_type").isNotNull())
             .withColumn("days_open", F.datediff(F.current_date(), "order_date"))
             .withColumn("priority", F.when((F.col("issue_type") == "delivery_overdue") & (
                 F.datediff(F.current_date(), "promised_delivery_date") > 3), "high")
                 .when(F.col("rating") == 1, "high").otherwise("normal"))
             .select("order_id", "customer_id", "order_date", "issue_type", "priority", "days_open",
                     "order_status", "warehouse_id", "carrier", "rating", "return_reason", "order_total"))
    _write(queue, "mart_cs_attention_queue")


def build_platform(spark: SparkSession) -> None:
    tables = [("bronze", t, config.bronze(t)) for t in config.STREAMS]
    tables += [("silver", t, config.silver(t)) for t in
               ("orders", "order_items", "order_events", "customers", "products", "quarantine")]
    tables += [("gold", t, config.gold(t)) for t in
               ("dim_date", "dim_product", "dim_customer", "fact_orders", "fact_order_items")]
    rows = []
    for layer, name, path in tables:
        if not DeltaTable.isDeltaTable(spark, path):
            continue
        table = DeltaTable.forPath(spark, path)
        last = table.history(1).select("timestamp", "version").first()
        rows.append((layer, name, table.toDF().count(), last["version"], last["timestamp"]))
    _write(spark.createDataFrame(rows, "layer string, table_name string, row_count long, "
                                       "delta_version long, last_updated timestamp"), "mart_table_stats")

    quarantine_path = config.silver("quarantine")
    if DeltaTable.isDeltaTable(spark, quarantine_path):
        _write(spark.read.format("delta").load(quarantine_path).groupBy("source_stream", "rejection_reason").agg(
            F.count("*").alias("records"), F.max("quarantined_at").alias("last_seen")), "mart_quarantine_summary")

    hourly = None
    for stream in config.STREAMS:
        df = spark.read.format("delta").load(config.bronze(stream)).groupBy(
            F.lit(stream).alias("stream"), F.date_trunc("hour", "ingested_at").alias("hour")).agg(
            F.count("*").alias("records"))
        hourly = df if hourly is None else hourly.unionByName(df)
    _write(hourly, "mart_ingestion_hourly")

    events = _silver(spark, "orders").select(F.date_trunc("hour", "order_ts").alias("hour")).groupBy("hour").agg(
        F.count("*").alias("orders"))
    _write(events, "mart_orders_hourly")


TARGETS = {
    "dimensions": build_dimensions,
    "facts": build_facts,
    "sales": build_sales,
    "marketing": build_marketing,
    "operations": build_operations,
    "finance": build_finance,
    "customer_service": build_customer_service,
    "platform": build_platform,
}


def run(spark: SparkSession, target: str) -> None:
    for name, build in TARGETS.items():
        if target in (name, "all"):
            print(f"Building gold target: {name}")
            build(spark)
