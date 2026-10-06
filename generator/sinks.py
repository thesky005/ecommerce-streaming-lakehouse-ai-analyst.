"""Destinations for simulated events: Kafka (streaming) or a file landing zone (local runs)."""
import os
import uuid
from collections import defaultdict
from pathlib import Path


class KafkaSink:
    def __init__(self, bootstrap_servers: str, client_id: str = "storefront-event-generator"):
        from confluent_kafka import Producer

        self._producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "client.id": client_id,
                "enable.idempotence": True,
                "acks": "all",
                "linger.ms": 50,
                "compression.type": "lz4",
            }
        )
        self.failed = 0

    def _on_delivery(self, error, message):
        if error is not None:
            self.failed += 1
            print(f"Delivery failed for key {message.key()}: {error}")

    def send(self, topic: str, key: str, value: str) -> None:
        while True:
            try:
                self._producer.produce(topic, key=key, value=value.encode("utf-8"), on_delivery=self._on_delivery)
                break
            except BufferError:
                self._producer.poll(0.5)
        self._producer.poll(0)

    def flush(self) -> None:
        self._producer.flush(30)

    def close(self) -> None:
        self.flush()


class FileSink:
    """Writes newline-delimited JSON files per topic, the same shape Spark's file source streams.

    Files are written under a dot-prefixed temporary name and renamed when complete, so a
    streaming reader never picks up a half-written file.
    """

    def __init__(self, landing_dir: str | Path, events_per_file: int = 2000):
        self.landing_dir = Path(landing_dir)
        self.events_per_file = events_per_file
        self._buffers: dict[str, list[str]] = defaultdict(list)

    def send(self, topic: str, key: str, value: str) -> None:
        buffer = self._buffers[topic]
        buffer.append(value.replace("\n", " "))
        if len(buffer) >= self.events_per_file:
            self._write(topic)

    def _write(self, topic: str) -> None:
        lines = self._buffers.pop(topic, [])
        if not lines:
            return
        directory = self.landing_dir / topic
        directory.mkdir(parents=True, exist_ok=True)
        name = f"part-{uuid.uuid4().hex}.json"
        temporary = directory / f".{name}.tmp"
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(temporary, directory / name)

    def flush(self) -> None:
        for topic in list(self._buffers):
            self._write(topic)

    def close(self) -> None:
        self.flush()
