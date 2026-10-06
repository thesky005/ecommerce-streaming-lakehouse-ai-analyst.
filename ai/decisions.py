"""AI-generated "Decisions needed" for a reporting period.

The agent is handed a KPI pack for the period and the prior period (computed with SQL so
the model starts from correct numbers), may run its own follow-up queries to dig into
causes, and must return a ranked list of decisions as JSON. Results are cached per
period and data version, because free LLM tiers allow only a limited number of calls.
"""
import json
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai.agent import DataAgent, data_window

SEVERITIES = {"high", "medium", "positive"}
DEPARTMENTS = {"sales": "Sales", "marketing": "Marketing", "operations": "Operations", "finance": "Finance",
               "customer service": "Customer service", "customer_service": "Customer service", "cs": "Customer service"}


def _period_sql(start, end) -> dict[str, str]:
    """Queries that build the KPI pack for one period [start, end]."""
    w = f"order_date BETWEEN DATE '{start}' AND DATE '{end}'"
    d = f"CAST(delivered_at AS DATE) BETWEEN DATE '{start}' AND DATE '{end}'"
    r = f"CAST(return_requested_at AS DATE) BETWEEN DATE '{start}' AND DATE '{end}'"
    return {
        "headline": f"""SELECT count(*) AS orders,
              round(sum(merchandise_amount) FILTER (WHERE order_status <> 'cancelled'), 0) AS net_sales,
              round(avg(merchandise_amount) FILTER (WHERE order_status <> 'cancelled'), 2) AS avg_order_value,
              sum(CASE WHEN is_new_customer THEN 1 ELSE 0 END) AS new_customers,
              round(sum(gross_profit) FILTER (WHERE paid_at IS NOT NULL AND order_status <> 'cancelled')
                    / nullif(sum(merchandise_amount) FILTER (WHERE paid_at IS NOT NULL AND order_status <> 'cancelled'), 0), 3) AS gross_margin,
              round(avg(CASE WHEN payment_failures > 0 THEN 1 ELSE 0 END), 3) AS payment_failure_rate,
              round(avg(CASE WHEN order_status = 'cancelled' THEN 1 ELSE 0 END), 3) AS cancellation_rate,
              round(avg(hours_to_ship), 1) AS avg_hours_to_ship
            FROM fact_orders WHERE {w}""",
        "delivery": f"""SELECT count(*) AS deliveries, round(1 - avg(CAST(is_late_delivery AS INT)), 3) AS on_time_rate,
              round(avg(rating), 2) AS avg_rating,
              round(avg(rating) FILTER (WHERE is_late_delivery), 2) AS avg_rating_late,
              round(avg(rating) FILTER (WHERE NOT is_late_delivery), 2) AS avg_rating_on_time
            FROM fact_orders WHERE {d}""",
        "returns": f"""SELECT (SELECT count(*) FROM fact_orders WHERE {r}) AS returns,
              round((SELECT count(*) FROM fact_orders WHERE {r}) / nullif((SELECT count(*) FROM fact_orders WHERE {d}), 0), 3) AS return_rate""",
        "by_channel": f"""SELECT channel, count(*) AS orders, round(sum(merchandise_amount), 0) AS net_sales
            FROM fact_orders WHERE {w} AND order_status <> 'cancelled' GROUP BY 1 ORDER BY 3 DESC""",
        "by_carrier": f"""SELECT carrier, count(*) AS deliveries, round(1 - avg(CAST(is_late_delivery AS INT)), 3) AS on_time_rate,
              round(avg(rating), 2) AS avg_rating FROM fact_orders WHERE {d} AND carrier IS NOT NULL GROUP BY 1 ORDER BY 3""",
        "by_warehouse": f"""SELECT warehouse_id, count(*) AS orders, round(avg(hours_to_ship), 1) AS avg_hours_to_ship,
              round(quantile_cont(hours_to_ship, 0.9), 1) AS p90_hours_to_ship
            FROM fact_orders WHERE {w} GROUP BY 1 ORDER BY 3 DESC""",
        "returns_by_category": f"""SELECT p.category, count(*) AS returns, mode(o.return_reason) AS top_reason
            FROM fact_orders o JOIN dim_product p ON p.sku = o.returned_sku WHERE {r.replace('return_requested_at', 'o.return_requested_at')}
            GROUP BY 1 ORDER BY 2 DESC""",
        "by_payment_method": f"""SELECT payment_method, count(*) AS orders,
              round(avg(CASE WHEN payment_failures > 0 THEN 1 ELSE 0 END), 3) AS failure_rate,
              sum(CASE WHEN cancel_reason = 'payment_failed' THEN 1 ELSE 0 END) AS orders_lost
            FROM fact_orders WHERE {w} GROUP BY 1 ORDER BY 3 DESC""",
        "by_campaign": f"""SELECT coalesce(campaign_id, '(none)') AS campaign, count(*) AS orders,
              round(sum(merchandise_amount), 0) AS revenue, round(sum(discount_amount), 0) AS discount,
              sum(CASE WHEN is_new_customer THEN 1 ELSE 0 END) AS new_customers
            FROM fact_orders WHERE {w} AND order_status <> 'cancelled' GROUP BY 1 ORDER BY 3 DESC""",
    }


def kpi_pack(agent: DataAgent, days: int) -> tuple[str, dict]:
    _, _, as_of = data_window(agent.warehouse)
    start = as_of - timedelta(days=days - 1)
    prior_start, prior_end = start - timedelta(days=days), start - timedelta(days=1)
    sections = []
    for label, (a, b) in (("CURRENT PERIOD", (start, as_of)), ("PRIOR PERIOD", (prior_start, prior_end))):
        sections.append(f"=== {label}: {a} to {b} ===")
        for name, sql in _period_sql(a, b).items():
            sections.append(f"-- {name}\n{agent.warehouse.query(sql)['text']}")
    period = {"start": str(start), "end": str(as_of), "prior_start": str(prior_start), "prior_end": str(prior_end)}
    return "\n".join(sections), period


INSTRUCTIONS = """

You are now preparing the "Decisions needed" briefing for the leadership dashboard. A KPI pack for the period is \
below. Use it as your starting point, and run follow-up queries (at most about four) where you need to understand a \
cause or size an impact, for example which products drive returns or which warehouse feeds a late carrier.

Pick the 4 to 6 most important decisions across Sales, Marketing, Operations, Finance and Customer service. Include \
problems against target and, where they exist, clear opportunities. Rank them by business impact. Each decision \
needs concrete evidence with numbers from the data and a specific, actionable recommendation with an owner.

Reply with only a JSON object (no prose before or after) in this shape:
{"summary": "one sentence on the overall state of the business this period",
 "decisions": [{"severity": "high" | "medium" | "positive",
                "department": "Sales" | "Marketing" | "Operations" | "Finance" | "Customer service",
                "title": "short headline",
                "evidence": "what the data shows, with numbers and the comparison",
                "action": "the recommended decision"}]}"""


def _parse(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("The model did not return a JSON object.")
    data = json.loads(text[start:end + 1])
    decisions = []
    for item in data.get("decisions", []):
        severity = str(item.get("severity", "medium")).lower()
        department = DEPARTMENTS.get(str(item.get("department", "")).strip().lower(), str(item.get("department", "")))
        if not item.get("title"):
            continue
        decisions.append({"sev": severity if severity in SEVERITIES else "medium", "dept": department,
                          "title": str(item["title"]), "evidence": str(item.get("evidence", "")),
                          "action": str(item.get("action", ""))})
    if not decisions:
        raise ValueError("The model returned no decisions.")
    order = {"high": 0, "medium": 1, "positive": 2}
    return {"summary": str(data.get("summary", "")), "decisions": sorted(decisions, key=lambda d: order[d["sev"]])}


class DecisionService:
    def __init__(self, agent: DataAgent, cache_file: Path):
        self.agent = agent
        self.cache_file = cache_file
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        try:
            self.cache = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.cache = {}

    def get(self, days: int, refresh: bool = False) -> dict:
        key = f"{self.agent.warehouse.version}|{self.agent.llm.model}|{days}"
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:  # concurrent requests for the same period share one generation
            if not refresh and key in self.cache:
                return {**self.cache[key], "cached": True}
            pack, period = kpi_pack(self.agent, days)
            result, parsed, error = None, None, None
            for attempt in range(2):
                prompt = f"Prepare the decisions briefing for {period['start']} to {period['end']} " \
                         f"(prior period {period['prior_start']} to {period['prior_end']})."
                if attempt:
                    prompt += " Your previous reply was not valid JSON. Reply with only the JSON object."
                result = self.agent.run(prompt, max_steps=7, system_extra=INSTRUCTIONS + "\n\nKPI PACK\n" + pack)
                try:
                    parsed = _parse(result.answer)
                    break
                except (ValueError, json.JSONDecodeError) as exc:
                    error = str(exc)
            if parsed is None:
                raise ValueError(f"Could not read the AI briefing: {error}")
            payload = {**parsed, "period": period, "model": self.agent.llm.model,
                       "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                       "queries": [s.__dict__ for s in result.steps], "llm_calls": result.llm_calls}
            self.cache[key] = payload
            try:
                self.cache_file.write_text(json.dumps(self.cache, default=str), encoding="utf-8")
            except OSError:
                pass
            return {**payload, "cached": False}
