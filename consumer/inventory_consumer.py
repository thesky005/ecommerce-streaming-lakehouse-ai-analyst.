import json
from confluent_kafka import Consumer

conf = {
    'bootstrap.servers': '127.0.0.1:9092',
    'group.id': 'inventory-service-group',
    'auto.offset.reset': 'earliest'
}

consumer = Consumer(conf)
consumer.subscribe(['orders'])

print("🎧 Inventory Consumer running... Waiting for events. Press Ctrl+C to exit.")

try:
    while True:
        msg = consumer.poll(timeout=1.0)

        if msg is None:
            continue
        if msg.error():
            print(f"Consumer error: {msg.error()}")
            continue

        order = json.loads(msg.value().decode('utf-8'))

        print(f"✅ RESERVED INVENTORY | Order ID: {order['order_id']} | "
              f"Item: {order['item_id']} | Qty: {order['quantity']} | "
              f"Price: ${order['total_price']} | [Partition {msg.partition()} @ Offset {msg.offset()}]")

except KeyboardInterrupt:
    print("\n🛑 Shutting down consumer...")
finally:
    consumer.close()