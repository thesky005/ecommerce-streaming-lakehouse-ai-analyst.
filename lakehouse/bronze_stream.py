"""Bronze: Spark Structured Streaming ingestion of raw events into append-only Delta tables.

One streaming query per topic. Payloads are stored exactly as received, together with
their source coordinates (Kafka partition/offset or landing file), so Bronze can always be
replayed. Checkpoints give exactly-once delivery into each Delta table.
"""
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.streaming import StreamingQuery

from lakehouse import config


def _from_kafka(spark: SparkSession, topic: str) -> DataFrame:
    return (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", config.KAFKA_BOOTSTRAP_SERVERS)
        .option("subscribe", topic)
        .option("startingOffsets", "earliest")
        .option("failOnDataLoss", "false")
        .option("maxOffsetsPerTrigger", 50000)
        .load()
        .select(
            F.col("key").cast("string").alias("event_key"),
            F.col("value").cast("string").alias("payload"),
            F.col("topic"),
            F.col("partition").alias("kafka_partition"),
            F.col("offset").alias("kafka_offset"),
            F.col("timestamp").alias("kafka_timestamp"),
            F.lit(None).cast("string").alias("source_file"),
        )
    )


def _from_files(spark: SparkSession, topic: str) -> DataFrame:
    directory = config.LAKE_ROOT / "landing" / topic
    Path(directory).mkdir(parents=True, exist_ok=True)
    return (
        spark.readStream.format("text")
        .option("maxFilesPerTrigger", 200)
        .load(config.landing_path(topic))
        .select(
            F.lit(None).cast("string").alias("event_key"),
            F.col("value").alias("payload"),
            F.lit(topic).alias("topic"),
            F.lit(None).cast("int").alias("kafka_partition"),
            F.lit(None).cast("long").alias("kafka_offset"),
            F.lit(None).cast("timestamp").alias("kafka_timestamp"),
            F.col("_metadata.file_path").alias("source_file"),
        )
        .where(F.length(F.trim("payload")) > 0)
    )


def start_bronze_streams(spark: SparkSession, source: str, once: bool) -> list[StreamingQuery]:
    queries = []
    for topic in config.TOPICS:
        raw = _from_kafka(spark, topic) if source == "kafka" else _from_files(spark, topic)
        stream = (
            raw.withColumn("ingested_at", F.current_timestamp())
            .withColumn("ingest_date", F.to_date("ingested_at"))
            .writeStream.format("delta")
            .queryName(f"bronze_{topic}")
            .outputMode("append")
            .partitionBy("ingest_date")
            .option("checkpointLocation", config.checkpoint_path(f"bronze_{topic}_{source}"))
        )
        stream = stream.trigger(availableNow=True) if once else stream.trigger(
            processingTime=config.BRONZE_TRIGGER_INTERVAL
        )
        queries.append(stream.start(config.bronze(topic)))
        print(f"Bronze stream for '{topic}' started from {source}")
    return queries


def run(spark: SparkSession, source: str, once: bool) -> None:
    queries = start_bronze_streams(spark, source, once)
    if once:
        for query in queries:
            query.awaitTermination()
            progress = query.recentProgress
            rows = sum(p["numInputRows"] for p in progress)
            print(f"{query.name}: ingested {rows} rows")
    else:
        spark.streams.awaitAnyTermination()
