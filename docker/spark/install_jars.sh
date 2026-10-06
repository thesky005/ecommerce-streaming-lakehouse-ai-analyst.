#!/bin/sh
# Bakes the Delta Lake and Kafka connector jars into PySpark's jars directory so no container
# downloads dependencies at runtime. Versions must match requirements/spark.txt.
set -eu

JARS_DIR="$(python -c 'import os, pyspark; print(os.path.join(os.path.dirname(pyspark.__file__), "jars"))')"
MAVEN="https://repo1.maven.org/maven2"

for artifact in \
    io/delta/delta-spark_2.12/3.2.1/delta-spark_2.12-3.2.1.jar \
    io/delta/delta-storage/3.2.1/delta-storage-3.2.1.jar \
    org/apache/spark/spark-sql-kafka-0-10_2.12/3.5.3/spark-sql-kafka-0-10_2.12-3.5.3.jar \
    org/apache/spark/spark-token-provider-kafka-0-10_2.12/3.5.3/spark-token-provider-kafka-0-10_2.12-3.5.3.jar \
    org/apache/kafka/kafka-clients/3.4.1/kafka-clients-3.4.1.jar \
    org/apache/commons/commons-pool2/2.11.1/commons-pool2-2.11.1.jar
do
    curl -fsSL -o "$JARS_DIR/$(basename "$artifact")" "$MAVEN/$artifact"
done
echo "Installed connector jars into $JARS_DIR"
