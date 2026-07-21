"""FastAPI chat dashboard. See docs/PHASE4.md 4.1 + Phase 4 multi-turn enhancement.
Run: python -m interfaces.dashboard.app"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents.orchestrator import run as run_orchestrator
from agents.schemas import AgentState
from detection.signal_detector import Signal, SignalDetector
from retrieval.metric_client import MetricClient

_DIR = Path(__file__).parent
_HISTORY_PATH = _DIR.parent.parent / "results" / "analysis_history.jsonl"
_CONVERSATIONS_DIR = _DIR.parent.parent / "results" / "conversations"
_ALERT_WINDOW_S = 900  # matches orchestrator's scheduled-trigger window

app = FastAPI(title="AI Copilot Dashboard")
app.mount("/static", StaticFiles(directory=_DIR / "static"), name="static")


class AskRequest(BaseModel):
    question: str
    conversation_id: Optional[str] = None


@app.get("/")
def index():
    return FileResponse(_DIR / "static" / "index.html")


@app.post("/ask")
def ask(req: AskRequest):
    state = run_orchestrator(
        AgentState(trigger_type="user_question", question=req.question, conversation_id=req.conversation_id)
    )
    return state.answer.model_dump()


@app.post("/conversations")
def create_conversation():
    return {"conversation_id": str(uuid.uuid4())}


@app.get("/conversations")
def list_conversations():
    if not _CONVERSATIONS_DIR.exists():
        return []
    convos = []
    for path in _CONVERSATIONS_DIR.glob("*.jsonl"):
        lines = path.read_text().strip().splitlines()
        if not lines:
            continue
        turns = [json.loads(line) for line in lines]
        convos.append(
            {
                "conversation_id": path.stem,
                "first_question": turns[0]["raw_q"],
                "ts": turns[-1]["ts"],
                "turn_count": len(turns),
            }
        )
    return sorted(convos, key=lambda c: c["ts"], reverse=True)


@app.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str):
    path = _CONVERSATIONS_DIR / f"{conversation_id}.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail="conversation not found")
    return [json.loads(line) for line in path.read_text().strip().splitlines()]


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
