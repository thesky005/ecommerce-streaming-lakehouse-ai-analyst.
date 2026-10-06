# Airflow 2.10 with Java and PySpark so tasks can spark-submit jobs to the Spark cluster.
# The Python minor version (3.11) must match the Spark image, because the driver runs here.
FROM apache/airflow:2.10.5-python3.11

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless procps \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s "$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")" /opt/java
ENV JAVA_HOME=/opt/java

USER airflow
COPY requirements/spark.txt /tmp/spark.txt
RUN pip install --no-cache-dir -r /tmp/spark.txt
COPY docker/spark/install_jars.sh /tmp/install_jars.sh
RUN sh /tmp/install_jars.sh

ENV LAKEHOUSE_JARS_BAKED=1 \
    PYTHONPATH=/opt/project
