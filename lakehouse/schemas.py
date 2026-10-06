"""Explicit event schemas. Timestamps are read as strings and parsed in Silver so that a bad
value is reported as a data-quality failure rather than silently becoming null."""
from pyspark.sql.types import (
    ArrayType,
    BooleanType,
    DoubleType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

ORDER_ITEM = StructType([
    StructField("line_id", IntegerType()),
    StructField("sku", StringType()),
    StructField("quantity", IntegerType()),
    StructField("unit_price", DoubleType()),
    StructField("discount_amount", DoubleType()),
])

ORDER_PLACED = StructType([
    StructField("event_id", StringType()),
    StructField("event_type", StringType()),
    StructField("event_time", StringType()),
    StructField("order_id", StringType()),
    StructField("customer_id", StringType()),
    StructField("channel", StringType()),
    StructField("device", StringType()),
    StructField("traffic_source", StringType()),
    StructField("campaign_id", StringType()),
    StructField("payment_method", StringType()),
    StructField("currency", StringType()),
    StructField("shipping_fee", DoubleType()),
    StructField("warehouse_id", StringType()),
    StructField("promised_delivery_date", StringType()),
    StructField("ship_to", StructType([
        StructField("city", StringType()),
        StructField("region", StringType()),
        StructField("country", StringType()),
    ])),
    StructField("items", ArrayType(ORDER_ITEM)),
])

ORDER_EVENT = StructType([
    StructField("event_id", StringType()),
    StructField("event_type", StringType()),
    StructField("event_time", StringType()),
    StructField("order_id", StringType()),
    StructField("amount", DoubleType()),
    StructField("reason", StringType()),
    StructField("carrier", StringType()),
    StructField("tracking_number", StringType()),
    StructField("warehouse_id", StringType()),
    StructField("sku", StringType()),
    StructField("quantity", IntegerType()),
    StructField("rating", IntegerType()),
])

CUSTOMER_EVENT = StructType([
    StructField("event_id", StringType()),
    StructField("event_type", StringType()),
    StructField("event_time", StringType()),
    StructField("customer_id", StringType()),
    StructField("city", StringType()),
    StructField("region", StringType()),
    StructField("country", StringType()),
    StructField("loyalty_tier", StringType()),
    StructField("marketing_opt_in", BooleanType()),
    StructField("acquisition_source", StringType()),
    StructField("signup_date", StringType()),
])

ORDER_EVENT_TYPES = (
    "payment_captured",
    "payment_failed",
    "order_cancelled",
    "order_shipped",
    "order_delivered",
    "return_requested",
    "refund_issued",
    "review_submitted",
)
CUSTOMER_EVENT_TYPES = ("customer_registered", "customer_updated")

# Columns every Bronze table carries, whatever the source.
BRONZE = StructType([
    StructField("event_key", StringType()),
    StructField("payload", StringType()),
    StructField("topic", StringType()),
    StructField("kafka_partition", IntegerType()),
    StructField("kafka_offset", LongType()),
    StructField("kafka_timestamp", TimestampType()),
    StructField("source_file", StringType()),
    StructField("ingested_at", TimestampType()),
])
