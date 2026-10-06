# Spark 3.5 (via PySpark) + Delta Lake 3.2 + Kafka connector, used for the standalone
# cluster (master/worker) and the Bronze streaming job.
FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless procps curl \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s "$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")" /opt/java
ENV JAVA_HOME=/opt/java

COPY requirements/spark.txt /tmp/spark.txt
RUN pip install --no-cache-dir -r /tmp/spark.txt
COPY docker/spark/install_jars.sh /tmp/install_jars.sh
RUN sh /tmp/install_jars.sh

ENV SPARK_HOME=/usr/local/lib/python3.11/site-packages/pyspark \
    LAKEHOUSE_JARS_BAKED=1 \
    PYSPARK_PYTHON=python3 \
    PYTHONPATH=/opt/project \
    HOME=/tmp
ENV PATH="${SPARK_HOME}/bin:${PATH}"
WORKDIR /opt/project
