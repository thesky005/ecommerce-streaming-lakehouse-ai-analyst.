"""SparkSession factory with Delta Lake enabled."""
import os
import sys

from lakehouse.config import PROJECT_ROOT

SPARK_VERSION = "3.5.3"
KAFKA_PACKAGE = f"org.apache.spark:spark-sql-kafka-0-10_2.12:{SPARK_VERSION}"


def _use_local_tools() -> None:
    """On Windows, point Spark at the portable Java and Hadoop helpers from scripts/setup_local.ps1."""
    tools = PROJECT_ROOT / ".tools"
    if os.name != "nt" or not tools.exists():
        return
    jdk = tools / "jdk"
    if jdk.exists() and not os.environ.get("JAVA_HOME"):
        os.environ["JAVA_HOME"] = str(jdk)
    hadoop = tools / "hadoop"
    if hadoop.exists():
        os.environ.setdefault("HADOOP_HOME", str(hadoop))
        os.environ["PATH"] = f"{hadoop / 'bin'}{os.pathsep}{os.environ['PATH']}"
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)


def build_spark(app_name: str):
    _use_local_tools()
    from pyspark.sql import SparkSession

    builder = (
        SparkSession.builder.appName(app_name)
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", os.getenv("SPARK_SHUFFLE_PARTITIONS", "8"))
        .config("spark.ui.showConsoleProgress", "false")
        .config("spark.driver.memory", os.getenv("SPARK_DRIVER_MEMORY", "2g"))
    )
    if os.name == "nt":
        log_config = (PROJECT_ROOT / "lakehouse" / "log4j2-windows.properties").as_uri()
        builder = (
            builder.config("spark.driver.host", "localhost")
            .config("spark.driver.bindAddress", "127.0.0.1")
            .config("spark.driver.extraJavaOptions", f"-Dlog4j2.configurationFile={log_config}")
        )
    if os.getenv("LAKEHOUSE_JARS_BAKED") == "1":
        # Docker images ship the Delta and Kafka jars inside Spark's jars directory.
        spark = builder.getOrCreate()
    else:
        from delta import configure_spark_with_delta_pip

        spark = configure_spark_with_delta_pip(builder, extra_packages=[KAFKA_PACKAGE]).getOrCreate()
    spark.sparkContext.setLogLevel(os.getenv("SPARK_LOG_LEVEL", "WARN"))
    return spark
