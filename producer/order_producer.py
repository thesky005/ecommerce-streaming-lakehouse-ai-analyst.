import json
import time
import random
from datetime import datetime, timezone
from confluent_kafka import Producer

def delivery_report(err, msg):
    if err is not None:
        print(f"❌ Delivery failed for order {msg.key()}: {err}")
    else:
        print(f"📦 Order published -> Partition: {msg.partition()} | Offset: {msg.offset()}")

# Using explicit IPv4 127.0.0.1 prevents Windows IPv6 resolution issues
conf = {
    'bootstrap.servers': '127.0.0.1:9092',
    'client.id': 'web-storefront-producer'
}

producer = Producer(conf)
topic_name = 'orders'

print("🚀 Starting E-Commerce Producer... Press Ctrl+C to exit.")

try:
    while True:
        order_event = {
            "order_id": f"ORD-{random.randint(10000, 99999)}",
            "customer_id": f"CUST-{random.randint(100, 999)}",
            "item_id": f"SKU-{random.randint(4000, 4999)}",
            "quantity": random.randint(1, 5),
            "total_price": round(random.uniform(15.0, 250.0), 2),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        producer.produce(
            topic=topic_name,
            key=order_event["order_id"],
            value=json.dumps(order_event).encode('utf-8'),
            callback=delivery_report
        )

        producer.poll(0)
        time.sleep(2)

except KeyboardInterrupt:
    print("\n🛑 Shutting down producer...")
finally:
    producer.flush()