"""Northstar Insights server: serves the dashboard and the AI endpoints.

    python -m ai.server          # then open http://localhost:8000

Endpoints
    GET  /                       the dashboard (showcase.html)
    GET  /api/health             whether the AI is configured, which model, data window
    POST /api/ask                {"question": "...", "history": [...]} -> answer + the queries it ran
    GET  /api/decisions?days=7   AI "Decisions needed" briefing for the period (cached)
    POST /api/reload             reload the Gold tables after a pipeline run
"""
import os
import threading
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from ai.agent import DataAgent, data_window  # noqa: E402
from ai.decisions import DecisionService  # noqa: E402
from ai.llm import LLMClient, LLMError  # noqa: E402
from ai.warehouse import Warehouse  # noqa: E402

app = FastAPI(title="Northstar Insights", docs_url="/api/docs")
_state: dict = {}
_lock = threading.Lock()


def services() -> tuple[DataAgent, DecisionService]:
    with _lock:
        if "agent" not in _state:
            warehouse = Warehouse()
            agent = DataAgent(warehouse, LLMClient())
            _state["agent"] = agent
            _state["decisions"] = DecisionService(agent, warehouse.lake_root / "_ai_decisions_cache.json")
        return _state["agent"], _state["decisions"]


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    history: list[dict] = Field(default_factory=list)


@app.get("/")
def dashboard():
    page = PROJECT_ROOT / "showcase.html"
    if not page.exists():
        raise HTTPException(404, "showcase.html not found. Run: python scripts/build_showcase.py")
    return FileResponse(page)


@app.get("/api/health")
def health():
    agent, _ = services()
    first, last, as_of = data_window(agent.warehouse)
    return {"ai": agent.llm.configured, "model": agent.llm.model, "provider": agent.llm.base_url,
            "data_from": str(first), "data_through": str(as_of), "tables": len(agent.warehouse.tables)}


@app.post("/api/ask")
def ask(request: AskRequest):
    agent, _ = services()
    if not agent.llm.configured:
        raise HTTPException(503, "AI is not configured. Add OPENROUTER_API_KEY to .env and restart the server.")
    try:
        result = agent.run(request.question, history=request.history)
    except LLMError as error:
        raise HTTPException(502, str(error)) from error
    return {"answer": result.answer, "steps": [s.__dict__ for s in result.steps],
            "llm_calls": result.llm_calls, "model": agent.llm.model}


@app.get("/api/decisions")
def decisions(days: int = 7, refresh: bool = False):
    if days not in (7, 14, 30):
        raise HTTPException(400, "days must be 7, 14 or 30")
    agent, service = services()
    if not agent.llm.configured:
        raise HTTPException(503, "AI is not configured. Add OPENROUTER_API_KEY to .env and restart the server.")
    try:
        return service.get(days, refresh=refresh)
    except LLMError as error:
        raise HTTPException(502, str(error)) from error
    except ValueError as error:
        raise HTTPException(502, str(error)) from error


@app.post("/api/reload")
def reload():
    agent, _ = services()
    agent.warehouse.reload()
    return {"reloaded": True, "tables": len(agent.warehouse.tables)}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("AI_SERVER_PORT", "8000"))
    print(f"Northstar Insights running at http://localhost:{port}")
    uvicorn.run(app, host=os.getenv("AI_SERVER_HOST", "127.0.0.1"), port=port, log_level="warning")
