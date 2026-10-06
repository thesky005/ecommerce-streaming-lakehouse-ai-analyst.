"""Delta table housekeeping: compact small files written by streaming, then vacuum old files."""
import os

from delta.tables import DeltaTable
from pyspark.sql import SparkSession

from lakehouse import config


def run(spark: SparkSession) -> None:
    retention_hours = int(os.getenv("VACUUM_RETENTION_HOURS", "168"))
    for layer in ("bronze", "silver", "gold"):
        layer_dir = config.LAKE_ROOT / layer
        if not layer_dir.exists():
            continue
        for table_dir in sorted(p for p in layer_dir.iterdir() if p.is_dir()):
            path = table_dir.as_uri()
            if not DeltaTable.isDeltaTable(spark, path):
                continue
            table = DeltaTable.forPath(spark, path)
            metrics = table.optimize().executeCompaction().select("metrics.numFilesRemoved", "metrics.numFilesAdded").first()
            table.vacuum(retention_hours)
            print(f"{layer}.{table_dir.name}: compacted {metrics[0]} files into {metrics[1]}, "
                  f"vacuumed files older than {retention_hours}h")
