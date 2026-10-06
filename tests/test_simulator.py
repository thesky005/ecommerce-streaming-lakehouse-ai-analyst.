import json
from datetime import datetime, timedelta, timezone

from generator.catalog import STREAM_CUSTOMERS, STREAM_ORDER_EVENTS, STREAM_ORDERS, load_products
from generator.simulator import StorefrontSimulator


class MemorySink:
    def __init__(self):
        self.records: list[tuple[str, str, str]] = []

    def send(self, stream, key, value):
        self.records.append((stream, key, value))

    def flush(self):
        pass


NOW = datetime.now(timezone.utc).replace(microsecond=0)


def simulate(days: float = 3, seed: int = 7, **kwargs) -> tuple[StorefrontSimulator, MemorySink]:
    simulator = StorefrontSimulator(load_products(), NOW - timedelta(days=days), seed=seed, **kwargs)
    simulator.seed_customers(200)
    sink = MemorySink()
    simulator.run(sink, live=False)
    return simulator, sink


def parsed(sink: MemorySink, stream: str) -> list[dict]:
    rows = []
    for record_stream, _, value in sink.records:
        if record_stream == stream:
            try:
                rows.append(json.loads(value))
            except json.JSONDecodeError:
                pass
    return rows


def test_same_seed_produces_identical_stream():
    _, first = simulate(seed=11)
    _, second = simulate(seed=11)
    assert [r[2] for r in first.records][:500] == [r[2] for r in second.records][:500]


def test_clean_stream_has_consistent_orders_and_lifecycle():
    _, sink = simulate(duplicate_rate=0, bad_record_rate=0)
    orders = {o["order_id"]: o for o in parsed(sink, STREAM_ORDERS)}
    events = parsed(sink, STREAM_ORDER_EVENTS)
    assert len(orders) > 100
    for event in events:
        order = orders[event["order_id"]]
        assert event["event_time"] >= order["event_time"], "lifecycle events never precede the order"
    shipped = {e["order_id"] for e in events if e["event_type"] == "order_shipped"}
    delivered = {e["order_id"] for e in events if e["event_type"] == "order_delivered"}
    assert delivered <= shipped
    for order in orders.values():
        assert order["items"] and all(item["quantity"] > 0 for item in order["items"])


def test_every_ordering_customer_is_registered_first():
    _, sink = simulate(duplicate_rate=0, bad_record_rate=0)
    registered = {c["customer_id"] for c in parsed(sink, STREAM_CUSTOMERS) if c["event_type"] == "customer_registered"}
    assert {o["customer_id"] for o in parsed(sink, STREAM_ORDERS)} <= registered


def test_dirty_data_is_injected_at_roughly_the_configured_rates():
    simulator, sink = simulate(days=5, duplicate_rate=0.02, bad_record_rate=0.02)
    corrupted = sum(v for k, v in simulator.stats.items() if k.startswith("corrupted_"))
    emitted = len(sink.records) - simulator.stats["duplicates"]
    assert 0.01 < corrupted / emitted < 0.03
    assert 0.01 < simulator.stats["duplicates"] / emitted < 0.03


def test_state_round_trip_resumes_without_replaying_history():
    simulator, _ = simulate(days=1)
    state = json.loads(json.dumps(simulator.to_state()))
    restored = StorefrontSimulator.from_state(load_products(), state)
    assert restored.clock == simulator.clock
    assert len(restored.customers) == len(simulator.customers)
    assert len(restored.pending) == len(simulator.pending)
    assert restored._order_counter == simulator._order_counter
