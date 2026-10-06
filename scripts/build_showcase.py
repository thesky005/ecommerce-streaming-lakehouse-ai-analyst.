"""Build showcase.html: the Northstar Commerce decision dashboard as one offline HTML file.

Reads the Gold Delta tables (via delta-rs, no Spark needed), packs order-level facts into a
compact columnar dataset, and inlines it with the dashboard app (showcase/app.js), styles,
diagrams and plotly.js. Every KPI, comparison and recommendation is computed in the browser
for the selected period, so the page behaves like the product rather than a static report.

    python scripts/run_local.py --fresh      # build the lake first
    python scripts/build_showcase.py         # writes showcase.html in the project root
"""
import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from deltalake import DeltaTable
from plotly.offline import get_plotlyjs

ROOT = Path(__file__).resolve().parents[1]
LAKE = Path(os.getenv("LAKE_ROOT", ROOT / "lake"))
ASSETS = ROOT / "showcase"


def gold(name: str) -> pd.DataFrame:
    path = LAKE / "gold" / name
    if not (path / "_delta_log").exists():
        raise SystemExit(f"Missing gold.{name}. Run `python scripts/run_local.py --fresh` first.")
    return DeltaTable(str(path)).to_pandas()


def clean(values) -> list:
    return [None if (v is None or (isinstance(v, float) and math.isnan(v))) else v for v in values]


def records(df: pd.DataFrame) -> list[dict]:
    return [{k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in row.items()}
            for row in df.to_dict("records")]


def encode(series: pd.Series) -> tuple[list, list[int]]:
    """Dictionary-encode a categorical column: (values, codes) with -1 for missing."""
    values = sorted(series.dropna().unique().tolist())
    lookup = {v: i for i, v in enumerate(values)}
    return values, [lookup[v] if pd.notna(v) else -1 for v in series]


def build_data() -> dict:
    orders = gold("fact_orders").sort_values("order_ts").reset_index(drop=True)
    items = gold("fact_order_items")
    base = pd.Timestamp(orders["order_ts"].min()).tz_convert(None).normalize()

    def day(column: str) -> list:
        ts = pd.to_datetime(orders[column], utc=True).dt.tz_convert(None).dt.normalize()
        return [None if pd.isna(v) else int(v) for v in (ts - base).dt.days]

    dicts, codes = {}, {}
    for key, column in (("ch", "channel"), ("src", "traffic_source"), ("cmp", "campaign_id"),
                        ("pay", "payment_method"), ("wh", "warehouse_id"), ("car", "carrier"),
                        ("reg", "ship_region"), ("st", "order_status"), ("rr", "return_reason"),
                        ("cr", "cancel_reason")):
        dicts[key], codes[key] = encode(orders[column])
    _, customer = encode(orders["customer_id"])

    order_index = {order_id: i for i, order_id in enumerate(orders["order_id"])}
    dicts["cat"], cat_codes = encode(items["category"])
    dicts["sku"], sku_codes = encode(items["sku"])
    names = items.drop_duplicates("sku").set_index("sku")["product_name"].to_dict()
    dicts["skuName"] = [names[s] for s in dicts["sku"]]

    order_day = day("order_ts")
    as_of = max(order_day) - 1  # last complete day; today is still filling up

    rfm = gold("mart_customer_rfm")
    segments = records(rfm.groupby("segment").agg(
        customers=("customer_id", "count"), revenue=("monetary", "sum"),
        recency=("recency_days", "mean"), frequency=("frequency", "mean")).reset_index())

    cohorts = gold("mart_customer_cohorts")
    grid = cohorts.pivot_table(index="cohort_week", columns="weeks_since_first", values="retention_pct")
    sizes = cohorts.groupby("cohort_week")["cohort_size"].max()

    queue = gold("mart_cs_attention_queue")
    queue = (queue.assign(rank=queue["priority"].map({"high": 0, "normal": 1}))
             .sort_values(["rank", "days_open"], ascending=[True, False]).head(12).drop(columns=["rank"]))
    queue["order_date"] = queue["order_date"].astype(str).str[:10]

    dq = gold("dq_check_results")
    latest = dq[dq["checked_at"] == dq["checked_at"].max()]
    run = json.loads((LAKE / "_last_run.json").read_text()) if (LAKE / "_last_run.json").exists() else {}

    return {
        "base": base.strftime("%Y-%m-%d"),
        "asOf": as_of,
        "dicts": dicts,
        "orders": {
            "d": order_day, "cust": customer, **codes,
            "new": orders["is_new_customer"].astype(int).tolist(),
            "merch": orders["merchandise_amount"].round(2).tolist(),
            "disc": orders["discount_amount"].round(2).tolist(),
            "ship": orders["shipping_fee"].round(2).tolist(),
            "cost": orders["cost_amount"].round(2).tolist(),
            "paid": orders["paid_at"].notna().astype(int).tolist(),
            "pfail": orders["payment_failures"].astype(int).tolist(),
            "canc": orders["cancelled_at"].notna().astype(int).tolist(),
            "shipH": clean(orders["hours_to_ship"].round(1).tolist()),
            "delD": day("delivered_at"),
            "daysDel": clean(orders["days_to_deliver"].round(2).tolist()),
            "late": [None if pd.isna(v) else int(v) for v in orders["is_late_delivery"]],
            "retD": day("return_requested_at"),
            "refund": orders["refund_amount"].round(2).tolist(),
            "refD": day("refunded_at"),
            "rating": [None if pd.isna(v) else int(v) for v in orders["rating"]],
        },
        "items": {
            "o": [order_index[o] for o in items["order_id"]],
            "cat": cat_codes, "sku": sku_codes,
            "qty": items["quantity"].astype(int).tolist(),
            "net": items["net_amount"].round(2).tolist(),
            "gp": items["gross_profit"].round(2).tolist(),
            "ret": items["is_returned_line"].eq(True).astype(int).tolist(),
        },
        "segments": segments,
        "cohorts": {"weeks": [int(c) for c in grid.columns],
                    "rows": [{"week": pd.Timestamp(w).strftime("%d %b"), "size": int(sizes[w]),
                              "values": clean([round(v * 100, 1) for v in grid.loc[w].tolist()])}
                             for w in grid.index]},
        "backlog": records(gold("mart_order_backlog").drop(columns=["snapshot_at"])),
        "queue": records(queue),
        "platform": {"checks": int(latest["passed"].sum()), "totalChecks": int(len(latest)),
                     "runSeconds": run.get("total_seconds"), "finishedAt": run.get("finished_at")},
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def build(output: Path) -> None:
    data = build_data()
    page = (ASSETS / "template.html").read_text(encoding="utf-8")
    replacements = {
        "/*{{CSS}}*/": (ASSETS / "styles.css").read_text(encoding="utf-8"),
        "<!--{{ARCHITECTURE}}-->": (ASSETS / "architecture.svg").read_text(encoding="utf-8"),
        "<!--{{DAG}}-->": (ASSETS / "dag.svg").read_text(encoding="utf-8"),
        "/*{{DATA}}*/": "const DATA = " + json.dumps(data, separators=(",", ":"), default=str) + ";",
        "/*{{APP}}*/": (ASSETS / "app.js").read_text(encoding="utf-8"),
        "/*{{PLOTLY}}*/": get_plotlyjs(),
    }
    for marker, content in replacements.items():
        page = page.replace(marker, content)
    output.write_text(page, encoding="utf-8")
    print(f"Wrote {output} ({output.stat().st_size / 1e6:.1f} MB, {len(data['orders']['d']):,} orders embedded)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=ROOT / "showcase.html")
    build(parser.parse_args().output)
