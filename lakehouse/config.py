"""Lake layout and runtime settings, all overridable with environment variables."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAKE_ROOT = Path(os.getenv("LAKE_ROOT", PROJECT_ROOT / "lake")).resolve()
REFERENCE_DIR = Path(os.getenv("REFERENCE_DIR", PROJECT_ROOT / "reference_data")).resolve()

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TOPICS = ("orders", "order_events", "customers")
BRONZE_TRIGGER_INTERVAL = os.getenv("BRONZE_TRIGGER_INTERVAL", "20 seconds")


def _uri(path: Path) -> str:
    return path.as_uri()


def landing_path(topic: str) -> str:
    return _uri(LAKE_ROOT / "landing" / topic)


def table_path(layer: str, name: str) -> str:
    return _uri(LAKE_ROOT / layer / name)


def checkpoint_path(name: str) -> str:
    return _uri(LAKE_ROOT / "_checkpoints" / name)


def bronze(topic: str) -> str:
    return table_path("bronze", topic)


def silver(name: str) -> str:
    return table_path("silver", name)


def gold(name: str) -> str:
    return table_path("gold", name)
