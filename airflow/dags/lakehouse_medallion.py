"""
### Lakehouse medallion pipeline

Bronze is filled continuously by the `spark-streaming` service (landing zone → Delta). Every ten
minutes this DAG turns the new Bronze data into curated tables on the Spark cluster:

1. **wait_for_bronze**: sensor that waits until the streaming job has created Bronze.
2. **silver**: incremental Structured Streaming batches (`availableNow`) that validate,
   quarantine, deduplicate and MERGE each entity; customers are kept as SCD Type 2.
3. **quality_gate**: uniqueness, referential-integrity, SCD2, quarantine-rate and freshness
   checks. A failed `error` check stops the run before Gold is touched.
4. **gold_core**: dimensions, then the order and order-line fact tables.
5. **department_marts**: one task per department, run in parallel.

Every Spark task goes through the `spark` pool, so the cluster is never oversubscribed.
"""
import os
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.sensors.python import PythonSensor
from airflow.utils.task_group import TaskGroup

PROJECT_DIR = os.getenv("PROJECT_DIR", "/opt/project")
LAKE_ROOT = Path(os.getenv("LAKE_ROOT", "/opt/lake"))
SPARK_MASTER_URL = os.getenv("SPARK_MASTER_URL", "spark://spark-master:7077")
SPARK_DRIVER_HOST = os.getenv("SPARK_DRIVER_HOST", "airflow-scheduler")
DEPARTMENTS = ["sales", "marketing", "operations", "finance", "customer_service", "platform"]


def spark_job(task_id: str, arguments: str, cores: int = 1, **kwargs) -> BashOperator:
    """Submit lakehouse/run.py to the standalone cluster in client mode (driver runs in Airflow)."""
    command = " ".join([
        "spark-submit",
        f"--master {SPARK_MASTER_URL}",
        f"--name {task_id}",
        "--driver-memory 1g",
        "--executor-memory 1g",
        f"--conf spark.cores.max={cores}",
        f"--conf spark.driver.host={SPARK_DRIVER_HOST}",
        "--conf spark.driver.bindAddress=0.0.0.0",
        "--conf spark.pyspark.python=python3",
        f"{PROJECT_DIR}/lakehouse/run.py {arguments}",
    ])
    return BashOperator(task_id=task_id, bash_command=command, pool="spark", **kwargs)


def bronze_ready() -> bool:
    return all((LAKE_ROOT / "bronze" / stream / "_delta_log").exists()
               for stream in ("orders", "order_events", "customers"))


with DAG(
    dag_id="lakehouse_medallion",
    description="Bronze → Silver → quality gate → Gold star schema and department marts",
    doc_md=__doc__,
    schedule="*/10 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "data-platform",
        "retries": 1,
        "retry_delay": timedelta(minutes=1),
        "execution_timeout": timedelta(minutes=20),
    },
    tags=["lakehouse", "spark", "delta", "medallion"],
) as dag:
    wait_for_bronze = PythonSensor(
        task_id="wait_for_bronze",
        python_callable=bronze_ready,
        poke_interval=30,
        timeout=15 * 60,
        mode="reschedule",
    )

    with TaskGroup("silver") as silver:
        products = spark_job("products", "silver --entity products")
        customers = spark_job("customers", "silver --entity customers")
        orders = spark_job("orders", "silver --entity orders", cores=2)
        order_events = spark_job("order_events", "silver --entity order_events", cores=2)
        products >> orders  # order validation checks SKUs against the latest catalogue

    quality_gate = spark_job("quality_gate", "quality")

    with TaskGroup("gold_core") as gold_core:
        spark_job("dimensions", "gold --target dimensions") >> spark_job("facts", "gold --target facts", cores=2)

    with TaskGroup("department_marts") as department_marts:
        for department in DEPARTMENTS:
            spark_job(department, f"gold --target {department}")

    wait_for_bronze >> silver >> quality_gate >> gold_core >> department_marts
