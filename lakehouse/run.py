"""Single entry point for every Spark job (used by spark-submit, Airflow and local runs).

    spark-submit lakehouse/run.py bronze --source kafka
    spark-submit lakehouse/run.py silver --entity orders
    spark-submit lakehouse/run.py quality
    spark-submit lakehouse/run.py gold --target sales
    spark-submit lakehouse/run.py maintenance
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lakehouse import bronze_stream, gold, maintenance, quality, silver  # noqa: E402
from lakehouse.spark import build_spark  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    jobs = parser.add_subparsers(dest="job", required=True)

    bronze = jobs.add_parser("bronze", help="stream raw events into Bronze Delta tables")
    bronze.add_argument("--source", choices=["kafka", "files"], default="kafka")
    bronze.add_argument("--once", action="store_true", help="process what is available, then stop")

    silver_job = jobs.add_parser("silver", help="validate, deduplicate and merge Bronze into Silver")
    silver_job.add_argument("--entity", choices=["products", "customers", "orders", "order_events", "all"],
                            default="all")

    jobs.add_parser("quality", help="run the data-quality gate on Silver")

    gold_job = jobs.add_parser("gold", help="build dimensional model and department marts")
    gold_job.add_argument("--target", choices=[*gold.TARGETS, "all"], default="all")

    jobs.add_parser("maintenance", help="OPTIMIZE and VACUUM every Delta table")

    args = parser.parse_args(argv)
    name = args.job + (f"_{getattr(args, 'entity', '') or getattr(args, 'target', '')}"
                       if args.job in ("silver", "gold") else "")
    spark = build_spark(f"lakehouse_{name}")
    try:
        if args.job == "bronze":
            bronze_stream.run(spark, args.source, args.once)
        elif args.job == "silver":
            silver.run(spark, args.entity)
        elif args.job == "quality":
            quality.run(spark)
        elif args.job == "gold":
            gold.run(spark, args.target)
        elif args.job == "maintenance":
            maintenance.run(spark)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
