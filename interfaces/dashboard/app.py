"""FastAPI chat dashboard. See docs/PHASE4.md 4.1. Run: python -m interfaces.dashboard.app"""
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents.orchestrator import run as run_orchestrator
from agents.schemas import AgentState
from detection.signal_detector import Signal, SignalDetector
from retrieval.metric_client import MetricClient

_DIR = Path(__file__).parent
_HISTORY_PATH = _DIR.parent.parent / "results" / "analysis_history.jsonl"
_ALERT_WINDOW_S = 900  # matches orchestrator's scheduled-trigger window

app = FastAPI(title="AI Copilot Dashboard")
app.mount("/static", StaticFiles(directory=_DIR / "static"), name="static")


class AskRequest(BaseModel):
    question: str


@app.get("/")
def index():
    return FileResponse(_DIR / "static" / "index.html")


@app.post("/ask")
def ask(req: AskRequest):
    state = run_orchestrator(AgentState(trigger_type="user_question", question=req.question))
    return state.answer.model_dump()


@app.get("/history")
def history():
    if not _HISTORY_PATH.exists():
        return []
    lines = _HISTORY_PATH.read_text().strip().splitlines()
    return [json.loads(line) for line in lines[-20:]][::-1]


@app.get("/resource-summary")
def resource_summary():
    end = time.time()
    return MetricClient().get_resource_summary(end - 300, end)


@app.get("/alerts")
def alerts():
    end = time.time()
    signals = SignalDetector().detect(end - _ALERT_WINDOW_S, end)
    return [_alert_view(s) for s in signals]


def _alert_view(s: Signal) -> dict:
    svc = ", ".join(s.affected_services)
    if s.signal_type == "cpu_high":
        detail = f"CPU at {s.metric_values.get('avg_cpu_pct', 0):.0f}%"
    elif s.signal_type == "memory_high":
        detail = f"memory at {s.metric_values.get('avg_memory_pct', 0):.0f}%"
    else:
        detail = s.signal_type.replace("_", " ")
    return {
        "signal_type": s.signal_type,
        "affected_services": s.affected_services,
        "message": f"{svc} {detail}",
        "question": f"What's wrong with {svc}? Signal detected: {detail}. What should we do?",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8500)
