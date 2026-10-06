"""Bronze: Spark Structured Streaming ingestion of raw events into append-only Delta tables.

The event generator writes newline-delimited JSON files into a landing zone, one folder per
event stream (orders, order_events, customers). One streaming query per stream picks up new
files, stores each payload exactly as received together with its source file, and appends
it to a Bronze Delta table. Checkpoints make every file land exactly once, so Bronze can
always be replayed.

    once=False  runs continuously, polling for new files every BRONZE_TRIGGER_INTERVAL
    once=True   processes whatever has arrived, then stops (availableNow trigger)
"""
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.streaming import StreamingQuery

from lakehouse import config


def _from_landing(spark: SparkSession, stream: str) -> DataFrame:
    Path(config.LAKE_ROOT / "landing" / stream).mkdir(parents=True, exist_ok=True)
    return (
        spark.readStream.format("text")
        .option("maxFilesPerTrigger", 200)
        .load(config.landing_path(stream))
        .select(
            F.col("value").alias("payload"),
            F.lit(stream).alias("stream"),
            F.col("_metadata.file_path").alias("source_file"),
        )
        .where(F.length(F.trim("payload")) > 0)
    )


def start_bronze_streams(spark: SparkSession, once: bool) -> list[StreamingQuery]:
    queries = []
    for stream in config.STREAMS:
        writer = (
            _from_landing(spark, stream)
            .withColumn("ingested_at", F.current_timestamp())
            .withColumn("ingest_date", F.to_date("ingested_at"))
            .writeStream.format("delta")
            .queryName(f"bronze_{stream}")
            .outputMode("append")
            .partitionBy("ingest_date")
            .option("checkpointLocation", config.checkpoint_path(f"bronze_{stream}"))
        )
        writer = writer.trigger(availableNow=True) if once else writer.trigger(
            processingTime=config.BRONZE_TRIGGER_INTERVAL
        )
        queries.append(writer.start(config.bronze(stream)))
        print(f"Bronze stream for '{stream}' started")
    return queries


def run(spark: SparkSession, once: bool) -> None:
    queries = start_bronze_streams(spark, once)
    if once:
        for query in queries:
            query.awaitTermination()
            rows = sum(p["numInputRows"] for p in query.recentProgress)
            print(f"{query.name}: ingested {rows} rows")
    else:
        spark.streams.awaitAnyTermination()
