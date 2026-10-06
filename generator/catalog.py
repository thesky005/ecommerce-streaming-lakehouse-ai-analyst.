"""Static reference data shared by the event simulator."""
import csv
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTS_CSV = PROJECT_ROOT / "reference_data" / "products.csv"

TOPIC_ORDERS = "orders"
TOPIC_ORDER_EVENTS = "order_events"
TOPIC_CUSTOMERS = "customers"
TOPICS = (TOPIC_ORDERS, TOPIC_ORDER_EVENTS, TOPIC_CUSTOMERS)


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    category: str
    brand: str
    unit_price: float
    unit_cost: float
    return_risk: float


def load_products(path: Path = PRODUCTS_CSV) -> list[Product]:
    with open(path, newline="", encoding="utf-8") as handle:
        return [
            Product(
                sku=row["sku"],
                name=row["product_name"],
                category=row["category"],
                brand=row["brand"],
                unit_price=float(row["unit_price"]),
                unit_cost=float(row["unit_cost"]),
                return_risk=float(row["return_risk"]),
            )
            for row in csv.DictReader(handle)
        ]


# city -> (region, fulfilling warehouse)
CITIES = {
    "Seattle": ("West", "WH-RENO"),
    "San Francisco": ("West", "WH-RENO"),
    "Los Angeles": ("West", "WH-RENO"),
    "Denver": ("West", "WH-RENO"),
    "Chicago": ("Midwest", "WH-COLUMBUS"),
    "Minneapolis": ("Midwest", "WH-COLUMBUS"),
    "Detroit": ("Midwest", "WH-COLUMBUS"),
    "Austin": ("South", "WH-DALLAS"),
    "Atlanta": ("South", "WH-DALLAS"),
    "Miami": ("South", "WH-DALLAS"),
    "Dallas": ("South", "WH-DALLAS"),
    "New York": ("Northeast", "WH-NEWARK"),
    "Boston": ("Northeast", "WH-NEWARK"),
    "Philadelphia": ("Northeast", "WH-NEWARK"),
}
CITY_WEIGHTS = [6, 4, 7, 3, 6, 2, 2, 3, 4, 3, 3, 9, 3, 3]
WAREHOUSES = ("WH-RENO", "WH-COLUMBUS", "WH-DALLAS", "WH-NEWARK")
# Typical pick-and-pack hours per warehouse (mean); Newark is the busiest site.
WAREHOUSE_PROCESSING_HOURS = {"WH-RENO": 14, "WH-COLUMBUS": 18, "WH-DALLAS": 16, "WH-NEWARK": 24}

# carrier -> (min transit days, max transit days, selection weight)
CARRIERS = {
    "SwiftShip": (1, 3, 3),
    "ParcelPro": (2, 4, 5),
    "EconoPost": (3, 7, 2),
}

CHANNELS = {"web": 50, "mobile_app": 35, "marketplace": 15}
TRAFFIC_SOURCES = {
    "organic_search": 28,
    "paid_search": 20,
    "direct": 18,
    "social": 14,
    "email": 12,
    "affiliate": 8,
}
PAYMENT_METHODS = {  # method -> (weight, failure probability)
    "card": (55, 0.03),
    "paypal": (20, 0.015),
    "apple_pay": (15, 0.01),
    "buy_now_pay_later": (6, 0.08),
    "bank_transfer": (4, 0.02),
}

RETURN_REASONS = {
    "Apparel": {"wrong_size": 55, "not_as_described": 15, "changed_mind": 20, "arrived_damaged": 5, "defective": 5},
    "Electronics": {"defective": 45, "not_as_described": 20, "changed_mind": 20, "arrived_damaged": 15},
    "default": {"changed_mind": 35, "not_as_described": 25, "arrived_damaged": 20, "defective": 20},
}

LOYALTY_TIERS = (("platinum", 2500), ("gold", 1000), ("silver", 300), ("bronze", 0))
