"""Deterministic tests for orchestrator wiring -- no LLM calls, no network for the graph
plumbing itself. The "scheduled -> zero signals -> zero LLM calls" test monkeypatches
SignalDetector; the graph-execution tests stub out run_analyst/build_graph so a missing
ANTHROPIC_API_KEY/DEEPSEEK_API_KEY can't make these fail."""
from agents import orchestrator
from agents.schemas import AgentState, AnalystAnswer
from detection.signal_detector import SignalDetector


def test_graph_builds():
    orchestrator.build_graph()  # raises if the node/edge wiring is broken


def test_needs_more_data_true_when_no_answer():
    assert orchestrator._needs_more_data(AgentState(trigger_type="user_question")) is True


def test_needs_more_data_false_when_answer_has_findings():
    state = AgentState(trigger_type="user_question")
    state.answer = AnalystAnswer(answer="short", findings=[{
        "category": "healthy", "summary": "ok", "evidence": ["x"], "severity": "info",
    }])
    assert orchestrator._needs_more_data(state) is False


def test_scheduled_with_no_signals_makes_zero_llm_calls(monkeypatch):
    monkeypatch.setattr(SignalDetector, "detect", lambda self, start, end: [])

    def _boom(*a, **kw):
        raise AssertionError("build_graph should never run when there are no signals")

    monkeypatch.setattr(orchestrator, "build_graph", _boom)

    result = orchestrator.run(AgentState(trigger_type="scheduled"))
    assert result.answer is None
    assert result.signals == []


def test_user_question_trace_id_is_extracted_before_graph_runs(monkeypatch):
    trace_id = "aa0a3d4773fc332d7590ef1d79c5937a"
    captured = {}

    class _FakeGraph:
        def invoke(self, state):
            captured["trace_id"] = state.trace_id
            return state.model_dump()

    monkeypatch.setattr(orchestrator, "build_graph", lambda: _FakeGraph())
    result = orchestrator.run(AgentState(trigger_type="user_question", question=f"anything wrong with trace {trace_id}?"))
    assert captured["trace_id"] == trace_id
    assert result.trace_id == trace_id
