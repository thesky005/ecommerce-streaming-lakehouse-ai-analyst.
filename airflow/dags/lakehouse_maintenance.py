"""
### Lakehouse maintenance

Nightly housekeeping for every Delta table: `OPTIMIZE` compacts the many small files that
streaming and frequent MERGEs produce, then `VACUUM` deletes files older than the retention
window (7 days), which keeps time travel available for a week.
"""
from datetime import datetime, timedelta

from airflow import DAG

from lakehouse_medallion import spark_job

with DAG(
    dag_id="lakehouse_maintenance",
    description="OPTIMIZE and VACUUM all Delta tables",
    doc_md=__doc__,
    schedule="0 3 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"owner": "data-platform", "retries": 1, "retry_delay": timedelta(minutes=5)},
    tags=["lakehouse", "delta", "maintenance"],
) as dag:
    spark_job("optimize_and_vacuum", "maintenance", cores=2, execution_timeout=timedelta(hours=1))
