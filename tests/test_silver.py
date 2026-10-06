"""Spark tests for the Silver layer: validation rules, quarantine, idempotent MERGE and SCD2."""
import json

import pytest

pyspark = pytest.importorskip("pyspark")

from lakehouse import config, silver  # noqa: E402
from lakehouse.schemas import BRONZE  # noqa: E402
from lakehouse.spark import build_spark  # noqa: E402

SKUS = ["SKU-1001", "SKU-2001"]


@pytest.fixture(scope="session")
def spark():
    session = build_spark("lakehouse_tests")
    yield session
    session.stop()


@pytest.fixture(autouse=True)
def lake(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LAKE_ROOT", tmp_path)
    return tmp_path


def bronze(spark, payloads):
    rows = [(None, p if isinstance(p, str) else json.dumps(p), "test", 0, i, None, None, None)
            for i, p in enumerate(payloads)]
    from pyspark.sql import functions as F

    return spark.createDataFrame(rows, BRONZE).withColumn("ingested_at", F.current_timestamp())


def order(order_id="ORD-1", **overrides):
    payload = {
        "event_id": f"e-{order_id}", "event_type": "order_placed", "event_time": "2026-09-01T10:00:00.000Z",
        "order_id": order_id, "customer_id": "CUST-1", "channel": "web", "device": "desktop",
        "traffic_source": "direct", "campaign_id": None, "payment_method": "card", "currency": "USD",
        "shipping_fee": 0.0, "warehouse_id": "WH-RENO", "promised_delivery_date": "2026-09-06",
        "ship_to": {"city": "Seattle", "region": "West", "country": "US"},
        "items": [{"line_id": 1, "sku": "SKU-1001", "quantity": 2, "unit_price": 10.0, "discount_amount": 1.0}],
    }
    payload.update(overrides)
    return payload


def customer(event_id, event_time, tier="bronze", city="Seattle"):
    return {"event_id": event_id, "event_type": "customer_updated", "event_time": event_time,
            "customer_id": "CUST-1", "city": city, "region": "West", "country": "US", "loyalty_tier": tier,
            "marketing_opt_in": True, "acquisition_source": "direct", "signup_date": "2026-01-01"}


def test_order_rules_assign_the_first_failing_reason(spark):
    bad_item = order("ORD-3")
    bad_item["items"][0]["quantity"] = -1
    unknown = order("ORD-4")
    unknown["items"][0]["sku"] = "SKU-9999"
    df = silver.validate_orders(bronze(spark, [
        order("ORD-1"),
        '{"event_id": "x", "order_id"',
        order("ORD-2", customer_id=None),
        bad_item,
        unknown,
        order("ORD-5", event_time="not-a-timestamp"),
    ]), SKUS)
    reasons = [r.rejection_reason for r in df.orderBy("kafka_offset").collect()]
    assert reasons == [None, "malformed_json", "missing_customer_id", "invalid_quantity", "unknown_sku",
                       "invalid_event_time"]


def test_orders_merge_is_idempotent_and_quarantines_rejects(spark, lake):
    batch = bronze(spark, [order("ORD-1"), order("ORD-1"), order("ORD-2", items=[])])
    silver.process_orders_batch(batch, 0, SKUS)
    silver.process_orders_batch(batch, 1, SKUS)  # replay of the same data must not duplicate rows
    orders = spark.read.format("delta").load(config.silver("orders"))
    items = spark.read.format("delta").load(config.silver("order_items"))
    assert orders.count() == 1
    assert items.count() == 1
    row = orders.first()
    assert (row.units, row.merchandise_amount) == (2, 19.0)
    quarantine = spark.read.format("delta").load(config.silver("quarantine"))
    assert [r.rejection_reason for r in quarantine.collect()] == ["empty_items", "empty_items"]


def test_customers_scd2_keeps_history_and_one_current_row(spark):
    silver.process_customers_batch(bronze(spark, [customer("c1", "2026-01-01T00:00:00Z")]), 0)
    silver.process_customers_batch(bronze(spark, [
        customer("c2", "2026-02-01T00:00:00Z", tier="silver"),
        customer("c3", "2026-02-15T00:00:00Z", tier="silver"),          # no attribute change: ignored
        customer("c4", "2026-03-01T00:00:00Z", tier="silver", city="Boston"),
        customer("c1", "2026-01-01T00:00:00Z"),                         # duplicate delivery: ignored
    ]), 1)
    rows = (spark.read.format("delta").load(config.silver("customers"))
            .orderBy("valid_from").collect())
    assert [(r.loyalty_tier, r.city, r.is_current) for r in rows] == [
        ("bronze", "Seattle", False), ("silver", "Seattle", False), ("silver", "Boston", True)]
    assert rows[0].valid_to == rows[1].valid_from
    assert rows[1].valid_to == rows[2].valid_from
    assert rows[2].valid_to is None
