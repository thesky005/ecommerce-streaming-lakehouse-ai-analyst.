"""Simulated storefront that emits customer, order, and order-lifecycle events.

The simulator keeps its own clock. It starts in the past (backfill) and replays history as
fast as possible, then switches to real time. Every order's future lifecycle (payment,
shipping, delivery, return, refund, review) is scheduled up front in a priority queue and
emitted when the clock reaches it, so late-arriving and out-of-order events happen
naturally. A small fraction of records is duplicated or corrupted on purpose so the Silver
layer has real data-quality work to do.
"""
import heapq
import json
import math
import random
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

from generator import catalog as C

# Relative order volume per hour of day and day of week (Mon..Sun), normalised to mean 1.
_HOURS = [0.25, 0.15, 0.1, 0.08, 0.08, 0.15, 0.35, 0.6, 0.85, 1.0, 1.1, 1.2,
          1.35, 1.3, 1.2, 1.15, 1.2, 1.35, 1.6, 1.8, 1.9, 1.7, 1.2, 0.6]
HOUR_PROFILE = [value * 24 / sum(_HOURS) for value in _HOURS]
WEEKDAY_PROFILE = [0.95, 0.9, 0.92, 0.97, 1.08, 1.2, 1.15]


class Sink(Protocol):
    def send(self, topic: str, key: str, value: str) -> None: ...
    def flush(self) -> None: ...


def iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def tier_for_spend(spend: float) -> str:
    return next(tier for tier, threshold in C.LOYALTY_TIERS if spend >= threshold)


@dataclass
class Customer:
    customer_id: str
    city: str
    loyalty_tier: str
    marketing_opt_in: bool
    acquisition_source: str
    signup_time: str
    lifetime_spend: float = 0.0
    orders: int = 0


class StorefrontSimulator:
    def __init__(
        self,
        products: list[C.Product],
        start: datetime,
        seed: int = 42,
        base_orders_per_hour: float = 7.5,
        duplicate_rate: float = 0.01,
        bad_record_rate: float = 0.006,
    ):
        self.rng = random.Random(seed)
        self.products = products
        self.by_sku = {product.sku: product for product in products}
        self.product_weights = [1 / math.sqrt(product.unit_price) for product in products]
        self.clock = start
        self.base_orders_per_hour = base_orders_per_hour
        self.duplicate_rate = duplicate_rate
        self.bad_record_rate = bad_record_rate
        self.customers: dict[str, Customer] = {}
        self.pending: list[tuple[datetime, int, str, str, dict]] = []
        self.stats: Counter = Counter()
        self._seq = 0
        self._order_counter = 0
        self._customer_counter = 0
        self._next_order: datetime | None = None

    # ------------------------------------------------------------------ helpers
    def _uuid(self) -> str:
        return uuid.UUID(int=self.rng.getrandbits(128), version=4).hex

    def _pick(self, mapping: dict) -> str:
        keys = list(mapping)
        weights = [value[0] if isinstance(value, tuple) else value for value in mapping.values()]
        return self.rng.choices(keys, weights=weights)[0]

    def _schedule(self, due: datetime, topic: str, key: str, payload: dict) -> None:
        self._seq += 1
        heapq.heappush(self.pending, (due, self._seq, topic, key, payload))

    def _campaign_flags(self, ts: datetime) -> tuple[bool, bool]:
        weekend_sale = ts.weekday() >= 4  # Friday to Sunday email promotion
        influencer_burst = ts.timetuple().tm_yday % 14 < 3
        return weekend_sale, influencer_burst

    def _order_rate(self, ts: datetime) -> float:
        weekend_sale, influencer_burst = self._campaign_flags(ts)
        boost = (1.15 if weekend_sale else 1.0) * (1.25 if influencer_burst else 1.0)
        return self.base_orders_per_hour * HOUR_PROFILE[ts.hour] * WEEKDAY_PROFILE[ts.weekday()] * boost

    def _next_order_time(self, after: datetime, multiplier: float) -> datetime:
        hours = self.rng.expovariate(self._order_rate(after) * multiplier)
        return after + timedelta(hours=hours)

    # ---------------------------------------------------------------- customers
    def _customer_event(self, event_type: str, ts: datetime, customer: Customer) -> dict:
        region, _ = C.CITIES[customer.city]
        return {
            "event_id": self._uuid(),
            "event_type": event_type,
            "event_time": iso(ts),
            "customer_id": customer.customer_id,
            "city": customer.city,
            "region": region,
            "country": "US",
            "loyalty_tier": customer.loyalty_tier,
            "marketing_opt_in": customer.marketing_opt_in,
            "acquisition_source": customer.acquisition_source,
            "signup_date": customer.signup_time[:10],
        }

    def _new_customer(self, signup: datetime, source: str, spend: float = 0.0, orders: int = 0) -> Customer:
        self._customer_counter += 1
        customer = Customer(
            customer_id=f"CUST-{self._customer_counter:06d}",
            city=self.rng.choices(list(C.CITIES), weights=C.CITY_WEIGHTS)[0],
            loyalty_tier=tier_for_spend(spend),
            marketing_opt_in=self.rng.random() < 0.6,
            acquisition_source=source,
            signup_time=iso(signup),
            lifetime_spend=spend,
            orders=orders,
        )
        self.customers[customer.customer_id] = customer
        return customer

    def seed_customers(self, count: int = 1200) -> None:
        """Create an existing customer base, registered up to 18 months before the start."""
        for _ in range(count):
            signup = self.clock - timedelta(days=self.rng.uniform(31, 540))
            spend = round(self.rng.lognormvariate(5.3, 1.0), 2)
            customer = self._new_customer(signup, self._pick(C.TRAFFIC_SOURCES), spend, self.rng.randint(1, 12))
            self._schedule(self.clock, C.TOPIC_CUSTOMERS, customer.customer_id,
                           self._customer_event("customer_registered", signup, customer))

    # ------------------------------------------------------------------- orders
    def _order_event(self, event_type: str, ts: datetime, order_id: str, **attributes) -> None:
        payload = {
            "event_id": self._uuid(),
            "event_type": event_type,
            "event_time": iso(ts),
            "order_id": order_id,
            "amount": None,
            "reason": None,
            "carrier": None,
            "tracking_number": None,
            "warehouse_id": None,
            "sku": None,
            "quantity": None,
            "rating": None,
        }
        payload.update(attributes)
        self._schedule(ts, C.TOPIC_ORDER_EVENTS, order_id, payload)

    def _place_order(self, ts: datetime, sink: Sink) -> None:
        rng = self.rng
        _, influencer_burst = self._campaign_flags(ts)
        weekend_sale, _ = self._campaign_flags(ts)

        if not self.customers or rng.random() < (0.4 if influencer_burst else 0.28):
            source = self._pick(C.TRAFFIC_SOURCES)
            customer = self._new_customer(ts - timedelta(minutes=rng.uniform(2, 30)), source)
            self._emit(sink, C.TOPIC_CUSTOMERS, customer.customer_id,
                       self._customer_event("customer_registered", parse_iso(customer.signup_time), customer))
            is_new = True
        else:
            pool = list(self.customers.values())
            customer = rng.choices(pool, weights=[1 + c.orders for c in pool])[0]
            source = self._pick(C.TRAFFIC_SOURCES)
            is_new = False
            if rng.random() < 0.012:  # customer moved: a slowly changing attribute for SCD2
                customer.city = rng.choices(list(C.CITIES), weights=C.CITY_WEIGHTS)[0]
                self._emit(sink, C.TOPIC_CUSTOMERS, customer.customer_id,
                           self._customer_event("customer_updated", ts - timedelta(minutes=5), customer))
        if source == "email" and not customer.marketing_opt_in:
            source = "direct"
        if is_new:
            source = customer.acquisition_source if customer.acquisition_source != "email" else "organic_search"

        campaign_id, discount_pct = None, 0.0
        if source == "paid_search":
            campaign_id = "CMP-SEARCH-ALWAYS-ON"
        elif source == "social":
            campaign_id = "CMP-SOCIAL-INFLUENCER" if influencer_burst else "CMP-SOCIAL-PROSPECTING"
            discount_pct = 0.10 if influencer_burst else 0.0
        elif source == "email":
            campaign_id = "CMP-EMAIL-WEEKEND-SALE" if weekend_sale else "CMP-EMAIL-NEWSLETTER"
            discount_pct = 0.15 if weekend_sale else 0.05
        elif source == "affiliate":
            campaign_id = "CMP-AFFILIATE-PARTNERS"
            discount_pct = 0.05
        if not discount_pct and customer.loyalty_tier in ("gold", "platinum") and rng.random() < 0.3:
            discount_pct = 0.05

        channel = self._pick(C.CHANNELS)
        if channel == "mobile_app":
            device = "mobile"
        else:
            device = rng.choices(["desktop", "mobile", "tablet"], weights=[55, 40, 5])[0]

        line_count = rng.choices([1, 2, 3, 4], weights=[60, 25, 10, 5])[0]
        chosen: list[C.Product] = []
        while len(chosen) < line_count:
            product = rng.choices(self.products, weights=self.product_weights)[0]
            if product not in chosen:
                chosen.append(product)
        items = []
        for line_id, product in enumerate(chosen, start=1):
            quantity = rng.choices([1, 2, 3], weights=[80, 15, 5] if product.unit_price > 60 else [55, 30, 15])[0]
            discount = round(product.unit_price * quantity * discount_pct, 2)
            items.append({"line_id": line_id, "sku": product.sku, "quantity": quantity,
                          "unit_price": product.unit_price, "discount_amount": discount})
        merchandise = round(sum(i["unit_price"] * i["quantity"] - i["discount_amount"] for i in items), 2)
        shipping_fee = 4.99 if channel == "marketplace" else (0.0 if merchandise >= 75 else 6.99)

        _, home_warehouse = C.CITIES[customer.city]
        fallback = rng.random() < 0.1  # stock-out at the nearest site
        warehouse = rng.choice([w for w in C.WAREHOUSES if w != home_warehouse]) if fallback else home_warehouse
        payment_method = self._pick(C.PAYMENT_METHODS)

        self._order_counter += 1
        order_id = f"ORD-{ts:%Y%m%d}-{self._order_counter:06d}"
        region, _ = C.CITIES[customer.city]
        order = {
            "event_id": self._uuid(),
            "event_type": "order_placed",
            "event_time": iso(ts),
            "order_id": order_id,
            "customer_id": customer.customer_id,
            "channel": channel,
            "device": device,
            "traffic_source": source,
            "campaign_id": campaign_id,
            "payment_method": payment_method,
            "currency": "USD",
            "shipping_fee": shipping_fee,
            "warehouse_id": warehouse,
            "promised_delivery_date": (ts + timedelta(days=8 if channel == "marketplace" else 6)).date().isoformat(),
            "ship_to": {"city": customer.city, "region": region, "country": "US"},
            "items": items,
        }
        self._emit(sink, C.TOPIC_ORDERS, order_id, order)
        self.stats["orders_placed"] += 1

        customer.orders += 1
        customer.lifetime_spend = round(customer.lifetime_spend + merchandise, 2)
        new_tier = tier_for_spend(customer.lifetime_spend)
        if new_tier != customer.loyalty_tier:
            customer.loyalty_tier = new_tier
            self._schedule(ts + timedelta(minutes=1), C.TOPIC_CUSTOMERS, customer.customer_id,
                           self._customer_event("customer_updated", ts + timedelta(minutes=1), customer))

        self._schedule_lifecycle(order, ts, merchandise + shipping_fee, fallback)

    def _schedule_lifecycle(self, order: dict, ts: datetime, total: float, fallback: bool) -> None:
        rng = self.rng
        order_id = order["order_id"]
        total = round(total, 2)
        _, failure_rate = C.PAYMENT_METHODS[order["payment_method"]]

        paid_at = ts + timedelta(seconds=rng.uniform(5, 90))
        if rng.random() < failure_rate:
            reason = rng.choice(["card_declined", "insufficient_funds", "authorization_timeout"])
            self._order_event("payment_failed", paid_at, order_id, amount=total, reason=reason)
            if rng.random() < 0.55:
                paid_at += timedelta(minutes=rng.uniform(10, 60))
            else:
                self._order_event("order_cancelled", paid_at + timedelta(hours=1), order_id, reason="payment_failed")
                return
        self._order_event("payment_captured", paid_at, order_id, amount=total)

        if rng.random() < 0.025:
            cancelled_at = paid_at + timedelta(hours=rng.uniform(0.5, 10))
            reason = rng.choice(["changed_mind", "found_cheaper", "ordered_by_mistake", "delivery_too_slow"])
            self._order_event("order_cancelled", cancelled_at, order_id, reason=reason)
            self._order_event("refund_issued", cancelled_at + timedelta(days=rng.uniform(1, 2)), order_id,
                              amount=total, reason="order_cancelled")
            return

        warehouse = order["warehouse_id"]
        mean_hours = C.WAREHOUSE_PROCESSING_HOURS[warehouse]
        processing = rng.gammavariate(2.0, mean_hours / 2)
        if ts.hour >= 16:
            processing += rng.uniform(6, 14)
        if ts.weekday() >= 5:
            processing += rng.uniform(8, 20)
        shipped_at = paid_at + timedelta(hours=processing)
        carrier = self._pick(C.CARRIERS)
        low, high, _ = C.CARRIERS[carrier]
        transit_days = rng.randint(low, high) + (rng.randint(1, 2) if fallback else 0)
        delivered_at = shipped_at + timedelta(days=transit_days, hours=rng.uniform(-4, 6))
        tracking = f"{carrier[:3].upper()}{rng.randint(10**9, 10**10 - 1)}"
        self._order_event("order_shipped", shipped_at, order_id, carrier=carrier,
                          tracking_number=tracking, warehouse_id=warehouse)
        self._order_event("order_delivered", delivered_at, order_id, carrier=carrier, tracking_number=tracking)
        late = delivered_at.date().isoformat() > order["promised_delivery_date"]

        risky = max(order["items"], key=lambda item: self.by_sku[item["sku"]].return_risk)
        product = self.by_sku[risky["sku"]]
        returned_reason = None
        if rng.random() < product.return_risk * (1.6 if late else 1.0):
            reasons = dict(C.RETURN_REASONS.get(product.category, C.RETURN_REASONS["default"]))
            if late:
                reasons["arrived_damaged"] = reasons.get("arrived_damaged", 5) * 2
            returned_reason = self._pick(reasons)
            requested_at = delivered_at + timedelta(days=rng.uniform(1, 14))
            refund = round(risky["unit_price"] * risky["quantity"] - risky["discount_amount"], 2)
            self._order_event("return_requested", requested_at, order_id, reason=returned_reason,
                              sku=risky["sku"], quantity=risky["quantity"], amount=refund)
            self._order_event("refund_issued", requested_at + timedelta(days=rng.uniform(2, 6)), order_id,
                              amount=refund, reason="return", sku=risky["sku"])

        if rng.random() < 0.32:
            rating = rng.choices([5, 4, 3, 2, 1], weights=[50, 28, 10, 6, 6])[0]
            if late and rng.random() < 0.6:
                rating = max(1, rating - rng.randint(1, 2))
            if returned_reason in ("defective", "arrived_damaged", "not_as_described"):
                rating = rng.choice([1, 1, 2, 3])
            self._order_event("review_submitted", delivered_at + timedelta(days=rng.uniform(1, 10)),
                              order_id, rating=rating, sku=order["items"][0]["sku"])

    # ----------------------------------------------------------------- emission
    def _corrupt(self, topic: str, payload: dict) -> str:
        broken = json.loads(json.dumps(payload))
        options = ["truncated_json", "bad_timestamp"]
        if topic == C.TOPIC_ORDERS:
            options += ["missing_customer_id", "negative_quantity", "unknown_sku"]
        elif topic == C.TOPIC_ORDER_EVENTS:
            options += ["unknown_event_type", "missing_order_id"]
        else:
            options += ["missing_customer_id"]
        kind = self.rng.choice(options)
        self.stats[f"corrupted_{kind}"] += 1
        if kind == "truncated_json":
            text = json.dumps(broken)
            return text[: len(text) // 2]
        if kind == "bad_timestamp":
            broken["event_time"] = "not-a-timestamp"
        elif kind == "missing_customer_id":
            broken.pop("customer_id", None)
        elif kind == "negative_quantity":
            broken["items"][0]["quantity"] = -broken["items"][0]["quantity"]
        elif kind == "unknown_sku":
            broken["items"][0]["sku"] = "SKU-9999"
        elif kind == "unknown_event_type":
            broken["event_type"] = "order_teleported"
        elif kind == "missing_order_id":
            broken.pop("order_id", None)
        return json.dumps(broken, separators=(",", ":"))

    def _emit(self, sink: Sink, topic: str, key: str, payload: dict) -> None:
        if self.rng.random() < self.bad_record_rate:
            value = self._corrupt(topic, payload)
        else:
            value = json.dumps(payload, separators=(",", ":"))
        sink.send(topic, key, value)
        self.stats[f"events_{topic}"] += 1
        if self.rng.random() < self.duplicate_rate:  # at-least-once delivery: same event twice
            sink.send(topic, key, value)
            self.stats["duplicates"] += 1

    # ---------------------------------------------------------------------- run
    def run(
        self,
        sink: Sink,
        *,
        live: bool,
        live_rate_multiplier: float = 30.0,
        checkpoint: Callable[[], None] | None = None,
        checkpoint_seconds: float = 30.0,
    ) -> None:
        """Replay history until now; then either stop (live=False) or continue in real time."""
        if self._next_order is None:
            self._next_order = self._next_order_time(self.clock, 1.0)
        last_flush = last_checkpoint = time.monotonic()
        while True:
            real_now = datetime.now(timezone.utc)
            due_event = self.pending[0][0] if self.pending else None
            next_time = min(t for t in (self._next_order, due_event) if t is not None)

            if next_time > real_now:
                if not live:
                    break
                time.sleep(min((next_time - real_now).total_seconds(), 1.0))
            elif due_event is not None and due_event <= self._next_order:
                due, _, topic, key, payload = heapq.heappop(self.pending)
                self.clock = max(self.clock, due)
                self._emit(sink, topic, key, payload)
            else:
                self.clock = self._next_order
                self._place_order(self.clock, sink)
                caught_up = self.clock >= real_now - timedelta(minutes=5)
                multiplier = live_rate_multiplier if live and caught_up else 1.0
                self._next_order = self._next_order_time(self.clock, multiplier)

            now = time.monotonic()
            if live and now - last_flush >= 5:
                sink.flush()
                last_flush = now
            if checkpoint and now - last_checkpoint >= checkpoint_seconds:
                checkpoint()
                last_checkpoint = now
        sink.flush()

    # -------------------------------------------------------------------- state
    def to_state(self) -> dict:
        version, internal, gauss = self.rng.getstate()
        return {
            # full precision (not iso()) so a resumed simulator continues exactly where it stopped
            "clock": self.clock.isoformat(),
            "next_order": self._next_order.isoformat() if self._next_order else None,
            "seq": self._seq,
            "order_counter": self._order_counter,
            "customer_counter": self._customer_counter,
            "rng": [version, list(internal), gauss],
            "customers": [asdict(c) for c in self.customers.values()],
            "pending": [[due.isoformat(), seq, topic, key, payload] for due, seq, topic, key, payload in self.pending],
        }

    @classmethod
    def from_state(cls, products: list[C.Product], state: dict, **kwargs) -> "StorefrontSimulator":
        simulator = cls(products, parse_iso(state["clock"]), **kwargs)
        version, internal, gauss = state["rng"]
        simulator.rng.setstate((version, tuple(internal), gauss))
        simulator._seq = state["seq"]
        simulator._order_counter = state["order_counter"]
        simulator._customer_counter = state["customer_counter"]
        simulator._next_order = parse_iso(state["next_order"]) if state["next_order"] else None
        simulator.customers = {c["customer_id"]: Customer(**c) for c in state["customers"]}
        simulator.pending = [(parse_iso(due), seq, topic, key, payload)
                             for due, seq, topic, key, payload in state["pending"]]
        heapq.heapify(simulator.pending)
        return simulator
