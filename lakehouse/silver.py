"""Silver: validated, deduplicated, conformed tables built incrementally from Bronze.

Each entity reads its Bronze table as a Delta stream with an `availableNow` trigger, so an
Airflow run processes exactly the Bronze rows that arrived since the previous run (the
checkpoint is the watermark). Inside `foreachBatch`:

* payloads are parsed against an explicit schema and checked against business rules;
* failing records go to `silver/quarantine` with a reason instead of being dropped;
* valid records are deduplicated and MERGEd, so replays and retries are idempotent;
* customers are kept as a Slowly Changing Dimension Type 2 history.
"""
from functools import reduce

from delta.tables import DeltaTable
from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from lakehouse import config, schemas


# --------------------------------------------------------------------- helpers
def _first_failure(rules: list[tuple[Column, str]]) -> Column:
    """Return the reason of the first failing rule, or null when every rule passes."""
    return reduce(lambda acc, rule: acc.when(rule[0], F.lit(rule[1])), rules[1:],
                  F.when(rules[0][0], F.lit(rules[0][1])))


def _common_rules(entity_key: str) -> list[tuple[Column, str]]:
    return [
        (F.get_json_object("payload", "$").isNull(), "malformed_json"),
        (F.col("data.event_id").isNull(), "missing_event_id"),
        (F.col(f"data.{entity_key}").isNull(), f"missing_{entity_key}"),
        (F.col("event_ts").isNull(), "invalid_event_time"),
        (F.col("event_ts") > F.current_timestamp() + F.expr("INTERVAL 1 DAY"), "event_time_in_future"),
    ]


def _parse(df: DataFrame, schema) -> DataFrame:
    return (
        df.withColumn("data", F.from_json("payload", schema))
        .withColumn("event_ts", F.to_timestamp("data.event_time"))
    )


def validate_orders(bronze_df: DataFrame, known_skus: list[str]) -> DataFrame:
    parsed = _parse(bronze_df, schemas.ORDER_PLACED)
    skus = F.array(*[F.lit(sku) for sku in known_skus])
    rules = _common_rules("order_id") + [
        (F.col("data.customer_id").isNull(), "missing_customer_id"),
        (F.coalesce(F.size("data.items"), F.lit(0)) < 1, "empty_items"),
        (F.exists("data.items", lambda i: F.coalesce(i.quantity, F.lit(0)) <= 0), "invalid_quantity"),
        (F.exists("data.items", lambda i: (F.coalesce(i.unit_price, F.lit(-1.0)) < 0)
                  | (F.coalesce(i.discount_amount, F.lit(0.0)) < 0)
                  | (i.discount_amount > i.unit_price * i.quantity)), "invalid_price"),
        (F.exists("data.items", lambda i: ~F.array_contains(skus, i.sku)), "unknown_sku"),
        (F.coalesce(F.col("data.shipping_fee"), F.lit(-1.0)) < 0, "invalid_shipping_fee"),
    ]
    return parsed.withColumn("rejection_reason", _first_failure(rules))


def validate_order_events(bronze_df: DataFrame) -> DataFrame:
    parsed = _parse(bronze_df, schemas.ORDER_EVENT)
    rules = _common_rules("order_id") + [
        (~F.coalesce(F.col("data.event_type").isin(*schemas.ORDER_EVENT_TYPES), F.lit(False)), "unknown_event_type"),
        ((F.col("data.event_type") == "review_submitted")
         & ~F.coalesce(F.col("data.rating").between(1, 5), F.lit(False)), "invalid_rating"),
        (F.col("data.amount") < 0, "negative_amount"),
    ]
    return parsed.withColumn("rejection_reason", _first_failure(rules))


def validate_customers(bronze_df: DataFrame) -> DataFrame:
    parsed = _parse(bronze_df, schemas.CUSTOMER_EVENT)
    rules = _common_rules("customer_id") + [
        (~F.coalesce(F.col("data.event_type").isin(*schemas.CUSTOMER_EVENT_TYPES), F.lit(False)),
         "unknown_event_type"),
    ]
    return parsed.withColumn("rejection_reason", _first_failure(rules))


def _ensure_table(spark: SparkSession, df: DataFrame, path: str, partition_by: list[str] | None = None) -> DeltaTable:
    if not DeltaTable.isDeltaTable(spark, path):
        df.limit(0).write.format("delta").partitionBy(*(partition_by or [])).save(path)
    return DeltaTable.forPath(spark, path)


def _merge_insert_only(spark: SparkSession, df: DataFrame, path: str, keys: list[str],
                       partition_by: list[str] | None = None) -> None:
    target = _ensure_table(spark, df, path, partition_by)
    condition = " AND ".join(f"t.{key} = s.{key}" for key in keys)
    target.alias("t").merge(df.alias("s"), condition).whenNotMatchedInsertAll().execute()


def _quarantine(validated: DataFrame, stream: str, batch_id: int) -> int:
    rejected = validated.where(F.col("rejection_reason").isNotNull()).select(
        F.lit(stream).alias("source_stream"),
        F.col("rejection_reason"),
        F.col("payload"),
        F.col("source_file"),
        F.col("ingested_at"),
        F.current_timestamp().alias("quarantined_at"),
    )
    count = rejected.count()
    if count:
        # Blind appends never conflict, so the three Silver jobs can share this table even when
        # Airflow runs them in parallel. txnAppId/txnVersion make a retried batch a no-op.
        (rejected.write.format("delta").mode("append").partitionBy("source_stream")
         .option("txnAppId", f"silver_quarantine_{stream}").option("txnVersion", batch_id)
         .save(config.silver("quarantine")))
    return count


# -------------------------------------------------------------------- entities
def process_orders_batch(batch: DataFrame, batch_id: int, known_skus: list[str]) -> None:
    spark = batch.sparkSession
    validated = validate_orders(batch, known_skus).persist()
    rejected = _quarantine(validated, "orders", batch_id)

    valid = (
        validated.where(F.col("rejection_reason").isNull())
        .withColumn("rn", F.row_number().over(Window.partitionBy("data.order_id").orderBy("ingested_at")))
        .where("rn = 1")
    )
    orders = valid.select(
        F.col("data.order_id").alias("order_id"),
        F.col("data.event_id").alias("event_id"),
        F.col("data.customer_id").alias("customer_id"),
        F.col("event_ts").alias("order_ts"),
        F.to_date("event_ts").alias("order_date"),
        F.col("data.channel").alias("channel"),
        F.col("data.device").alias("device"),
        F.col("data.traffic_source").alias("traffic_source"),
        F.col("data.campaign_id").alias("campaign_id"),
        F.col("data.payment_method").alias("payment_method"),
        F.col("data.currency").alias("currency"),
        F.col("data.shipping_fee").alias("shipping_fee"),
        F.col("data.warehouse_id").alias("warehouse_id"),
        F.to_date("data.promised_delivery_date").alias("promised_delivery_date"),
        F.col("data.ship_to.city").alias("ship_city"),
        F.col("data.ship_to.region").alias("ship_region"),
        F.col("data.ship_to.country").alias("ship_country"),
        F.size("data.items").alias("line_count"),
        F.aggregate("data.items", F.lit(0), lambda acc, i: acc + i.quantity).alias("units"),
        F.round(F.aggregate("data.items", F.lit(0.0),
                            lambda acc, i: acc + i.unit_price * i.quantity - i.discount_amount), 2)
        .alias("merchandise_amount"),
        F.col("ingested_at"),
        F.current_timestamp().alias("processed_at"),
    )
    items = valid.select(
        F.col("data.order_id").alias("order_id"),
        F.to_date("event_ts").alias("order_date"),
        F.explode("data.items").alias("item"),
    ).select(
        "order_id",
        "order_date",
        F.col("item.line_id").alias("line_id"),
        F.col("item.sku").alias("sku"),
        F.col("item.quantity").alias("quantity"),
        F.col("item.unit_price").alias("unit_price"),
        F.col("item.discount_amount").alias("discount_amount"),
        F.round(F.col("item.unit_price") * F.col("item.quantity") - F.col("item.discount_amount"), 2)
        .alias("net_amount"),
    )
    _merge_insert_only(spark, orders, config.silver("orders"), ["order_id"], ["order_date"])
    _merge_insert_only(spark, items, config.silver("order_items"), ["order_id", "line_id"], ["order_date"])
    print(f"silver.orders batch {batch_id}: {valid.count()} valid, {rejected} quarantined")
    validated.unpersist()


def process_order_events_batch(batch: DataFrame, batch_id: int) -> None:
    spark = batch.sparkSession
    validated = validate_order_events(batch).persist()
    rejected = _quarantine(validated, "order_events", batch_id)
    events = (
        validated.where(F.col("rejection_reason").isNull())
        .withColumn("_event_id", F.col("data.event_id")).dropDuplicates(["_event_id"])
        .select(
            F.col("data.event_id").alias("event_id"),
            F.col("data.order_id").alias("order_id"),
            F.col("data.event_type").alias("event_type"),
            F.col("event_ts"),
            F.to_date("event_ts").alias("event_date"),
            F.col("data.amount").alias("amount"),
            F.col("data.reason").alias("reason"),
            F.col("data.carrier").alias("carrier"),
            F.col("data.tracking_number").alias("tracking_number"),
            F.col("data.warehouse_id").alias("warehouse_id"),
            F.col("data.sku").alias("sku"),
            F.col("data.quantity").alias("quantity"),
            F.col("data.rating").alias("rating"),
            F.col("ingested_at"),
            F.current_timestamp().alias("processed_at"),
        )
    )
    _merge_insert_only(spark, events, config.silver("order_events"), ["event_id"], ["event_date"])
    print(f"silver.order_events batch {batch_id}: {events.count()} valid, {rejected} quarantined")
    validated.unpersist()


CUSTOMER_ATTRIBUTES = ["city", "region", "country", "loyalty_tier", "marketing_opt_in", "acquisition_source"]


def process_customers_batch(batch: DataFrame, batch_id: int) -> None:
    """SCD Type 2: every change to a tracked attribute closes the current row and opens a new one."""
    spark = batch.sparkSession
    validated = validate_customers(batch).persist()
    rejected = _quarantine(validated, "customers", batch_id)

    changes = (
        validated.where(F.col("rejection_reason").isNull())
        .withColumn("_event_id", F.col("data.event_id")).dropDuplicates(["_event_id"])
        .select(
            F.col("data.customer_id").alias("customer_id"),
            *[F.col(f"data.{name}").alias(name) for name in CUSTOMER_ATTRIBUTES],
            F.to_date("data.signup_date").alias("signup_date"),
            F.col("event_ts").alias("valid_from"),
        )
        .withColumn("record_hash", F.sha2(F.concat_ws("||", *[F.col(c).cast("string") for c in CUSTOMER_ATTRIBUTES]), 256))
    )
    empty = (changes.withColumn("valid_to", F.lit(None).cast("timestamp"))
             .withColumn("is_current", F.lit(True))
             .withColumn("customer_sk", F.lit(None).cast("string")))
    target = _ensure_table(spark, empty, config.silver("customers"))

    current = target.toDF().where("is_current").select(
        "customer_id", F.col("record_hash").alias("current_hash"), F.col("valid_from").alias("current_from"))
    by_customer = Window.partitionBy("customer_id").orderBy("valid_from")
    new_versions = (
        changes.join(current, "customer_id", "left")
        # late events older than the current version cannot rewrite history here
        .where(F.col("current_from").isNull() | (F.col("valid_from") > F.col("current_from")))
        .withColumn("previous_hash", F.coalesce(F.lag("record_hash").over(by_customer), F.col("current_hash")))
        .where(F.col("previous_hash").isNull() | (F.col("previous_hash") != F.col("record_hash")))
        .drop("current_hash", "current_from", "previous_hash")
        .withColumn("valid_to", F.lead("valid_from").over(by_customer))
        .withColumn("is_current", F.col("valid_to").isNull())
        .withColumn("customer_sk", F.sha2(F.concat_ws("|", "customer_id", F.col("valid_from").cast("string")), 256))
    ).persist()

    closes = (new_versions.withColumn("rn", F.row_number().over(by_customer)).where("rn = 1")
              .select(F.col("customer_id").alias("merge_key"), F.col("valid_from").alias("close_at")))
    inserts = new_versions.withColumn("merge_key", F.lit(None).cast("string")).withColumn(
        "close_at", F.lit(None).cast("timestamp"))
    staged = inserts.unionByName(closes, allowMissingColumns=True)

    versions = new_versions.count()  # count before the MERGE, which changes what this lazy plan reads
    columns = [c for c in empty.columns]
    (
        target.alias("t")
        .merge(staged.alias("s"), "t.customer_id = s.merge_key AND t.is_current = true")
        .whenMatchedUpdate(set={"valid_to": "s.close_at", "is_current": "false"})
        .whenNotMatchedInsert(condition="s.merge_key IS NULL", values={c: f"s.{c}" for c in columns})
        .execute()
    )
    print(f"silver.customers batch {batch_id}: {versions} new versions, {rejected} quarantined")
    new_versions.unpersist()
    validated.unpersist()


def load_products(spark: SparkSession) -> None:
    """Reference data snapshot (in production this would come from the product catalogue DB)."""
    products = (
        spark.read.option("header", True).option("inferSchema", True)
        .csv((config.REFERENCE_DIR / "products.csv").as_uri())
        .withColumn("loaded_at", F.current_timestamp())
    )
    products.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(config.silver("products"))
    print(f"silver.products: {products.count()} products loaded")


def _run_incremental(spark: SparkSession, stream: str, handler) -> None:
    query = (
        spark.readStream.format("delta").load(config.bronze(stream))
        .writeStream.foreachBatch(handler)
        .option("checkpointLocation", config.checkpoint_path(f"silver_{stream}"))
        .trigger(availableNow=True)
        .start()
    )
    query.awaitTermination()


def run(spark: SparkSession, entity: str) -> None:
    if entity in ("products", "all"):
        load_products(spark)
    if entity in ("customers", "all"):
        _run_incremental(spark, "customers", process_customers_batch)
    if entity in ("orders", "all"):
        if not DeltaTable.isDeltaTable(spark, config.silver("products")):
            load_products(spark)
        known_skus = [row.sku for row in spark.read.format("delta").load(config.silver("products")).collect()]
        _run_incremental(spark, "orders", lambda df, batch_id: process_orders_batch(df, batch_id, known_skus))
    if entity in ("order_events", "all"):
        _run_incremental(spark, "order_events", process_order_events_batch)
