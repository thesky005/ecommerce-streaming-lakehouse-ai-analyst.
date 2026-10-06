"""Data-analyst agent: answers questions by writing and running SQL against the Gold layer.

The model never sees the data up front. It gets the table descriptions and two tools
(run_sql, describe_table), decides what to query, reads the results, and keeps going until
it can answer. Every query and its outcome is recorded in the returned trace, so the UI
can show exactly where each number came from.
"""
import json
from dataclasses import dataclass, field
from datetime import date, timedelta

from ai.llm import LLMClient, LLMError
from ai.warehouse import QueryError, Warehouse

TARGETS = ("on-time delivery ≥ 90%, average hours to ship ≤ 24 h, return rate ≤ 6%, average rating ≥ 4.0, "
           "gross margin ≥ 50%, payment failure rate ≤ 3%, net sales growth ≥ +5% vs the prior period")

TOOLS = [
    {"type": "function", "function": {
        "name": "run_sql",
        "description": "Run one read-only DuckDB SELECT query against the warehouse and get up to 200 result rows. "
                       "Aggregate in SQL rather than fetching raw rows.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "A single DuckDB SELECT statement."},
            "purpose": {"type": "string", "description": "One short sentence: what this query is for."},
        }, "required": ["query", "purpose"]},
    }},
    {"type": "function", "function": {
        "name": "describe_table",
        "description": "Show a table's columns, types and three sample rows.",
        "parameters": {"type": "object", "properties": {
            "table": {"type": "string", "description": "Table name, e.g. fact_orders."},
        }, "required": ["table"]},
    }},
]


@dataclass
class Step:
    tool: str
    purpose: str
    query: str
    ok: bool
    rows: int = 0
    error: str = ""
    preview: str = ""


@dataclass
class AgentResult:
    answer: str
    steps: list[Step] = field(default_factory=list)
    llm_calls: int = 0


def data_window(warehouse: Warehouse) -> tuple[date, date, date]:
    first, last = warehouse.query("SELECT min(order_date), max(order_date) FROM fact_orders")["rows"][0]
    return first, last, last - timedelta(days=1)  # the newest day is still filling up


def system_prompt(warehouse: Warehouse) -> str:
    first, last, as_of = data_window(warehouse)
    return f"""You are the data analyst agent inside Northstar Insights, the business intelligence product of \
Northstar Commerce, a US online retailer (the company and data are fictional/synthetic).

You answer questions from managers using only the data in the warehouse, which you query with the run_sql tool \
(DuckDB SQL dialect, read-only). Orders run from {first} to {last}; the last complete day is {as_of}. Unless the \
user says otherwise, "last 7 days" means {as_of - timedelta(days=6)} to {as_of}, and comparisons are against the \
equally long period just before. Timestamps are UTC and money is USD.

Business plan targets: {TARGETS}.

How to work:
- Decide what you need, then query. Prefer one well-aggregated query over many small ones, and always LIMIT \
row-level queries.
- Every figure in your answer must come from a query result in this conversation. Never estimate or invent numbers. \
If the data cannot answer the question, say what is missing.
- If a query fails, read the error, fix the SQL and try again.
- Your final answer: start with the direct answer in one or two sentences, then the supporting figures as short \
bullets or a small markdown table, then a concrete recommendation when one is useful. State the period you used. \
Keep it concise and in plain business language, not SQL.

Warehouse tables:
{warehouse.schema_text()}"""


class DataAgent:
    def __init__(self, warehouse: Warehouse, llm: LLMClient):
        self.warehouse = warehouse
        self.llm = llm

    def _run_tool(self, name: str, raw_arguments: str) -> tuple[str, Step]:
        try:
            args = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError:
            return "Error: tool arguments were not valid JSON.", Step(name, "", raw_arguments or "", False,
                                                                      error="invalid JSON arguments")
        if name == "describe_table":
            table = str(args.get("table", ""))
            text = self.warehouse.describe(table)
            return text, Step(name, f"Inspect {table}", table, True)
        if name == "run_sql":
            query, purpose = str(args.get("query", "")), str(args.get("purpose", ""))
            try:
                result = self.warehouse.query(query)
            except QueryError as error:
                return f"Query error: {error}", Step(name, purpose, query, False, error=str(error))
            return result["text"], Step(name, purpose, query, True, rows=len(result["rows"]),
                                        preview="\n".join(result["text"].splitlines()[:6]))
        return f"Error: unknown tool {name}.", Step(name, "", "", False, error="unknown tool")

    def run(self, question: str, history: list[dict] | None = None, max_steps: int = 8,
            system_extra: str = "") -> AgentResult:
        messages = [{"role": "system", "content": system_prompt(self.warehouse) + system_extra}]
        for turn in (history or [])[-6:]:
            if turn.get("role") in ("user", "assistant") and turn.get("content"):
                messages.append({"role": turn["role"], "content": str(turn["content"])[:4000]})
        messages.append({"role": "user", "content": question})

        result, start_calls = AgentResult(answer=""), self.llm.calls
        for _ in range(max_steps):
            message = self.llm.chat(messages, tools=TOOLS)
            tool_calls = message.get("tool_calls") or []
            assistant = {"role": "assistant", "content": message.get("content") or ""}
            if tool_calls:
                assistant["tool_calls"] = tool_calls
            if message.get("reasoning_details"):
                assistant["reasoning_details"] = message["reasoning_details"]  # passed back unmodified
            messages.append(assistant)
            if not tool_calls:
                result.answer = (message.get("content") or "").strip()
                if result.answer:
                    break
                messages.append({"role": "user", "content": "Please write your final answer now."})
                continue
            for call in tool_calls:
                text, step = self._run_tool(call["function"]["name"], call["function"].get("arguments", "{}"))
                result.steps.append(step)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": text})
        if not result.answer:
            messages.append({"role": "user", "content": "You have used all your query steps. Answer now using only "
                                                        "the results you already have, and say if anything is unverified."})
            result.answer = (self.llm.chat(messages).get("content") or "").strip() or \
                "I could not complete the analysis within the step limit. Try a more specific question."
        result.llm_calls = self.llm.calls - start_calls
        return result


__all__ = ["DataAgent", "AgentResult", "Step", "LLMError", "data_window"]
