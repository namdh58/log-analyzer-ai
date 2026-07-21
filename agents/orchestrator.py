"""LangGraph orchestrator: build_context -> analyze -> (retry if low-content && loop_count<2) -> persist.
See docs/PHASE3.md 3.5."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import requests
from langgraph.graph import END, StateGraph

from agents.analyst import analyze as run_analyst
from agents.context_builder import build_context
from agents.schemas import AgentState
from detection.signal_detector import SignalDetector

_TRACE_ID_RE = re.compile(r"\b[0-9a-f]{32}\b", re.IGNORECASE)
_HISTORY_PATH = Path(__file__).parent.parent / "results" / "analysis_history.jsonl"
_SCHEDULED_WINDOW_S = 900


def _needs_more_data(state: AgentState) -> bool:
    if state.answer is None:
        return True
    return len(state.answer.answer.strip()) < 40 and not state.answer.findings


def _build_context_node(state: AgentState) -> dict:
    return {"context": build_context(state)}


def _analyze_node(state: AgentState) -> dict:
    return {"answer": run_analyst(state)}


def _route(state: AgentState) -> str:
    return "retry" if (_needs_more_data(state) and state.loop_count < 2) else "persist"


def _retry_node(state: AgentState) -> dict:
    return {"loop_count": state.loop_count + 1}


def _persist_node(state: AgentState) -> dict:
    _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": time.time(),
        "trigger_type": state.trigger_type,
        "question": state.question,
        "trace_id": state.trace_id,
        **state.answer.model_dump(),
    }
    with _HISTORY_PATH.open("a") as f:
        f.write(json.dumps(record) + "\n")
    _push_to_loki(record)
    return {}


def _push_to_loki(record: dict) -> None:
    loki_url = os.environ.get("LOKI_URL", "http://localhost:3100")
    line = json.dumps(
        {
            "trigger_type": record["trigger_type"],
            "answer": record["answer"][:300],
            "requires_human_review": record["requires_human_review"],
        }
    )
    now_ns = str(int(time.time() * 1e9))
    try:
        requests.post(
            f"{loki_url}/loki/api/v1/push",
            json={"streams": [{"stream": {"service_name": "ai-copilot"}, "values": [[now_ns, line]]}]},
            timeout=5,
        )
    except requests.RequestException as e:
        print(f"warning: failed to push analysis log to Loki: {e}")


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("build_context", _build_context_node)
    g.add_node("analyze", _analyze_node)
    g.add_node("retry", _retry_node)
    g.add_node("persist", _persist_node)
    g.set_entry_point("build_context")
    g.add_edge("build_context", "analyze")
    g.add_conditional_edges("analyze", _route, {"retry": "retry", "persist": "persist"})
    g.add_edge("retry", "build_context")
    g.add_edge("persist", END)
    return g.compile()


def run(state: AgentState) -> AgentState:
    """Entry point. Resolves trigger_type per PHASE3.md 3.5, then runs the graph."""
    if state.trigger_type == "user_question" and state.question and not state.trace_id:
        match = _TRACE_ID_RE.search(state.question)
        if match:
            state = state.model_copy(update={"trace_id": match.group(0)})

    if state.trigger_type == "scheduled":
        end = time.time()
        start = end - _SCHEDULED_WINDOW_S
        signals = SignalDetector().detect(start, end)
        if not signals:
            return state  # zero LLM calls -- quiet window, nothing to report
        state = state.model_copy(
            update={"signals": [s.model_dump() for s in signals], "time_range": (str(start), str(end))}
        )

    result = build_graph().invoke(state)
    return AgentState(**result)
