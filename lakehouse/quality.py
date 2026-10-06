"""Data-quality gate between Silver and Gold.

Each check yields an observed value that is compared with a threshold. Results are appended
to `gold/dq_check_results` for the Data Platform report page. A failed check with severity
`error` raises, which fails the Airflow task and stops Gold from publishing bad numbers.
"""
import os
import uuid
from dataclasses import dataclass

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from lakehouse import config


@dataclass
class CheckResult:
    check_name: str
    table_name: str
    severity: str
    passed: bool
    observed_value: float
    threshold: float
    details: str


def _duplicates(spark, path: str, keys: list[str]) -> int:
    df = spark.read.format("delta").load(path)
    return df.groupBy(*keys).count().where("count > 1").count()


def _orphan_rate(spark, child: str, parent: str, key: str) -> float:
    children = spark.read.format("delta").load(child).select(key)
    parents = spark.read.format("delta").load(parent).select(key).distinct()
    total = children.count()
    orphans = children.join(parents, key, "left_anti").count()
    return orphans / total if total else 0.0


def run_checks(spark: SparkSession) -> list[CheckResult]:
    s = config.silver
    results = [
        CheckResult("unique_order_id", "silver.orders", "error",
                    (v := _duplicates(spark, s("orders"), ["order_id"])) == 0, v, 0,
                    "order_id must identify exactly one order"),
        CheckResult("unique_order_line", "silver.order_items", "error",
                    (v := _duplicates(spark, s("order_items"), ["order_id", "line_id"])) == 0, v, 0,
                    "(order_id, line_id) must be unique"),
        CheckResult("unique_event_id", "silver.order_events", "error",
                    (v := _duplicates(spark, s("order_events"), ["event_id"])) == 0, v, 0,
                    "duplicate deliveries must be removed"),
    ]

    customers = spark.read.format("delta").load(s("customers"))
    multi_current = customers.where("is_current").groupBy("customer_id").count().where("count > 1").count()
    results.append(CheckResult("single_current_customer_version", "silver.customers", "error",
                               multi_current == 0, multi_current, 0, "SCD2 allows one current row per customer"))
    bad_ranges = customers.where("valid_to IS NOT NULL AND valid_to <= valid_from").count()
    results.append(CheckResult("valid_scd2_ranges", "silver.customers", "error",
                               bad_ranges == 0, bad_ranges, 0, "valid_to must be after valid_from"))

    unknown_sku = _orphan_rate(spark, s("order_items"), s("products"), "sku")
    results.append(CheckResult("order_items_known_sku", "silver.order_items", "error",
                               unknown_sku == 0, unknown_sku, 0, "every SKU must exist in the product catalogue"))
    orphan_customers = _orphan_rate(spark, s("orders"), s("customers"), "customer_id")
    results.append(CheckResult("orders_known_customer", "silver.orders", "warn",
                               orphan_customers <= 0.02, round(orphan_customers, 4), 0.02,
                               "share of orders whose customer record is missing (late or quarantined)"))
    orphan_events = _orphan_rate(spark, s("order_events"), s("orders"), "order_id")
    results.append(CheckResult("order_events_known_order", "silver.order_events", "warn",
                               orphan_events <= 0.02, round(orphan_events, 4), 0.02,
                               "share of lifecycle events whose order was quarantined"))

    negative = spark.read.format("delta").load(s("orders")).where("merchandise_amount < 0").count()
    results.append(CheckResult("non_negative_order_value", "silver.orders", "error",
                               negative == 0, negative, 0, "order value after discount cannot be negative"))

    bronze_rows = sum(spark.read.format("delta").load(config.bronze(t)).count() for t in config.TOPICS)
    quarantined = spark.read.format("delta").load(s("quarantine")).count() if _exists(spark, s("quarantine")) else 0
    rate = quarantined / bronze_rows if bronze_rows else 0.0
    results.append(CheckResult("quarantine_rate", "silver.quarantine", "error", rate <= 0.05,
                               round(rate, 4), 0.05, "share of Bronze records rejected by validation"))

    freshness_limit = float(os.getenv("FRESHNESS_MINUTES", "30"))
    # Computed in Spark: collecting a timestamp to Python would shift it into the machine's local zone.
    ages = [
        spark.read.format("delta").load(config.bronze(t))
        .agg((F.unix_timestamp(F.current_timestamp()) - F.unix_timestamp(F.max("ingested_at"))) / 60).first()[0]
        for t in config.TOPICS
    ]
    age = min((a for a in ages if a is not None), default=1e9)
    results.append(CheckResult("bronze_freshness_minutes", "bronze.*", "warn", age <= freshness_limit,
                               round(age, 1), freshness_limit, "minutes since the last event reached Bronze"))
    return results


def _exists(spark, path: str) -> bool:
    from delta.tables import DeltaTable

    return DeltaTable.isDeltaTable(spark, path)


def run(spark: SparkSession) -> None:
    results = run_checks(spark)
    run_id = os.getenv("AIRFLOW_CTX_DAG_RUN_ID") or f"manual__{uuid.uuid4().hex[:8]}"
    rows = [(run_id, r.check_name, r.table_name, r.severity, r.passed, float(r.observed_value),
             float(r.threshold), r.details) for r in results]
    df = spark.createDataFrame(rows, "run_id string, check_name string, table_name string, severity string, "
                                     "passed boolean, observed_value double, threshold double, details string")
    df = df.select("run_id", F.current_timestamp().alias("checked_at"), *df.columns[1:])
    df.write.format("delta").mode("append").save(config.gold("dq_check_results"))

    for r in results:
        status = "PASS" if r.passed else ("FAIL" if r.severity == "error" else "WARN")
        print(f"[{status}] {r.check_name:<34} observed={r.observed_value:<10} threshold={r.threshold}")
    failures = [r.check_name for r in results if not r.passed and r.severity == "error"]
    if failures:
        raise RuntimeError(f"Data-quality gate failed: {', '.join(failures)}")
