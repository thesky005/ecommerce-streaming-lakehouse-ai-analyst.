"""Storefront event generator: writes simulated store events into the landing zone.

Examples:
    python -m generator --backfill-days 30 --no-live     # replay 30 days of history, then stop
    python -m generator --live                           # replay history, then keep producing live events
"""
import argparse
import json
import os
import signal
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from generator.catalog import PROJECT_ROOT, load_products
from generator.sinks import FileSink
from generator.simulator import StorefrontSimulator


def env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--landing-dir", default=os.getenv("LANDING_DIR", str(PROJECT_ROOT / "lake" / "landing")))
    parser.add_argument("--backfill-days", type=float, default=float(os.getenv("BACKFILL_DAYS", "30")))
    parser.add_argument("--live", action=argparse.BooleanOptionalAction, default=env_bool("GENERATOR_LIVE", True),
                        help="keep producing in real time after the backfill catches up")
    parser.add_argument("--live-rate-multiplier", type=float,
                        default=float(os.getenv("LIVE_RATE_MULTIPLIER", "30")),
                        help="order-rate multiplier once caught up, so a live demo has visible traffic")
    parser.add_argument("--state-file", default=os.getenv("GENERATOR_STATE_FILE"),
                        help="resume from / save simulator state here so restarts do not replay history")
    parser.add_argument("--seed", type=int, default=int(os.getenv("GENERATOR_SEED", "42")))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    products = load_products()
    state_path = Path(args.state_file) if args.state_file else None

    if state_path and state_path.exists():
        simulator = StorefrontSimulator.from_state(products, json.loads(state_path.read_text()), seed=args.seed)
        print(f"Resuming simulation from {simulator.clock.isoformat()}")
    else:
        start = datetime.now(timezone.utc) - timedelta(days=args.backfill_days)
        simulator = StorefrontSimulator(products, start, seed=args.seed)
        simulator.seed_customers()
        print(f"Starting simulation at {start.isoformat()} ({args.backfill_days:g} days of backfill)")

    sink = FileSink(args.landing_dir)
    print(f"Writing events to the landing zone at {args.landing_dir}")

    def save_state() -> None:
        if state_path:
            sink.flush()
            state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(simulator.to_state()))
            os.replace(temporary, state_path)

    # Docker stops containers with SIGTERM; turn it into a normal exit so state is saved.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        simulator.run(sink, live=args.live, live_rate_multiplier=args.live_rate_multiplier, checkpoint=save_state)
    except KeyboardInterrupt:
        pass
    finally:
        sink.close()
        save_state()
        print("Generator stats:", json.dumps(dict(sorted(simulator.stats.items())), indent=2))


if __name__ == "__main__":
    main()
