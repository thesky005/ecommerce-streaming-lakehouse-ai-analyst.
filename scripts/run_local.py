"""Run the whole medallion pipeline locally without Docker, Kafka or Airflow.

The generator writes events to a file landing zone instead of Kafka; Bronze reads it with
the same Structured Streaming job (file source, availableNow trigger); then Silver, the
quality gate and Gold run in order, exactly as the Airflow DAG would.

    python scripts/run_local.py --fresh --days 30   # rebuild everything from scratch
    python scripts/run_local.py                      # add events since the last run, refresh
    streamlit run report/Home.py                     # open the department report
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lakehouse import bronze_stream, config, gold, quality, silver  # noqa: E402
from lakehouse.spark import build_spark  # noqa: E402


TIMINGS: dict[str, float] = {}


def step(title: str) -> float:
    print(f"\n=== {title} ===", flush=True)
    return time.perf_counter()


def timed(name: str, started: float) -> None:
    TIMINGS[name] = round(time.perf_counter() - started, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fresh", action="store_true", help="delete the local lake first")
    parser.add_argument("--days", type=float, default=30, help="days of history to simulate on a fresh run")
    args = parser.parse_args()

    if args.fresh and config.LAKE_ROOT.exists():
        shutil.rmtree(config.LAKE_ROOT)

    started = step("1/5 Generate events into the landing zone")
    subprocess.run(
        [sys.executable, "-m", "generator", "--sink", "files", "--no-live",
         "--landing-dir", str(config.LAKE_ROOT / "landing"),
         "--state-file", str(config.LAKE_ROOT / "_generator_state.json"),
         "--backfill-days", str(args.days)],
        cwd=ROOT, check=True,
    )
    timed("Generate events", started)

    t = time.perf_counter()
    spark = build_spark("lakehouse_local")
    timed("Spark startup", t)
    try:
        t = step("2/5 Bronze: Structured Streaming ingest (availableNow)")
        bronze_stream.run(spark, "files", once=True)
        timed("Bronze", t)
        t = step("3/5 Silver: validate, quarantine, deduplicate, MERGE, SCD2")
        silver.run(spark, "all")
        timed("Silver", t)
        t = step("4/5 Data-quality gate")
        quality.run(spark)
        timed("Quality gate", t)
        t = step("5/5 Gold: star schema and department marts")
        gold.run(spark, "all")
        timed("Gold", t)
    finally:
        spark.stop()

    total = time.perf_counter() - started
    summary = {"finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "fresh": args.fresh,
               "total_seconds": round(total, 1), "steps": TIMINGS}
    (config.LAKE_ROOT / "_last_run.json").write_text(json.dumps(summary, indent=2))
    print(f"\nPipeline finished in {total:.0f}s. Lake: {config.LAKE_ROOT}")
    print("Open the report with:  .venv\\Scripts\\streamlit run report\\Home.py")


if __name__ == "__main__":
    main()
