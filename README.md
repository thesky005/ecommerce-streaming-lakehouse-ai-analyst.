# Real-Time E-Commerce Order Ingestion Platform

A lightweight, real-time event-driven data pipeline built with **Apache Kafka (KRaft mode)** and **Python**. This project demonstrates transitioning a legacy batch-processed order system into an event-driven architecture to enable instant inventory reservation.

---

## 💡 Business Problem

A traditional e-commerce platform processed customer orders via nightly batch jobs. This caused a 24-hour delay in updating inventory systems, frequently leading to:
* **Overselling out-of-stock items** during peak sales events.
* **Delayed order fulfillments** due to batch job backlogs.

### The Solution
By introducing an **event-driven architecture using Apache Kafka**, order events published by the web application are immediately made available to downstream services (such as inventory management) with sub-second latency.

---

## 🏗️ System Architecture

```text
+-------------------+             +-----------------------+             +-----------------------+
|  Web Storefront   |             |     Apache Kafka      |             |   Inventory Service   |
|    (Producer)     | ========>   |   (Broker in KRaft)   | ========>   |      (Consumer)       |
|  order_producer   |  [Events]   |     Topic: orders     |  [Polls]    |  inventory_consumer   |
+-------------------+             +-----------------------+             +-----------------------+
                                        Partitions: 1
                                    Replication Factor: 1
```

---

## 🛠️ Tech Stack

* **Streaming Platform:** Apache Kafka 7.5 (KRaft mode)
* **Language:** Python 3.10+
* **Kafka Client Library:** 'confluent-kafka'
* **Containerization:** Docker & Docker Compose

---

## 🎓 Key Kafka Concepts Demonstrated

* **Event Producers:** Asynchronous event generation using delivery callbacks to confirm message publication without blocking execution.
* **Event Consumers:** Continuous message polling (`poll()`) and offset tracking managed via consumer groups.
* **KRaft Architecture:** Running a modern Kafka cluster without ZooKeeper dependencies.
* **At-Least-Once Delivery Semantics:** Ensuring message delivery reliability through producer acknowledgement handling (`acks`).
* **Decoupled Architecture:** Downstream consumers can go offline for maintenance without losing incoming web orders.

---

## 🚀 How to Run Locally

### Prerequisites
* [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.
* [Python 3.10+](https://www.python.org/) installed.

### 1. Clone the Repository
```bash
git clone [https://github.com/YOUR_GITHUB_USERNAME/ecommerce-order-ingestion.git](https://github.com/YOUR_GITHUB_USERNAME/ecommerce-order-ingestion.git)
cd ecommerce-order-ingestion
```

### 2. Start Kafka Cluster
```bash
cd docker
docker compose up -d
cd ..
```

### 3. Install Python Dependencies
```bash
pip install -r producer/requirements.txt
```

### 4. Run the Pipeline
Open two separate terminal windows:

* **Terminal 1 (Producer):**
  ```bash
  python producer/order_producer.py
  ```

* **Terminal 2 (Consumer):**
  ```bash
  python consumer/inventory_consumer.py
  ```



