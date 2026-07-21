"""Live check (against the real running stack) that context_builder fetches real
telemetry into the right shape per question type -- this is what keeps the analyst
grounded, so the test asserts on the ACTUAL structure the LLM prompt gets built from."""
from agents.context_builder import _format_service_row, build_context, render_context
from agents.schemas import AgentState

FIXTURE_TRACE_ID = "aa0a3d4773fc332d7590ef1d79c5937a"  # same real trace used in test_retrieval.py


def test_general_question_pulls_resource_summary():
    state = AgentState(trigger_type="user_question", question="how is the system doing?")
    context = build_context(state)
    assert context["mode"] == "general"
    assert len(context["resource_summary"]) > 0
    assert "window" in context
    rendered = render_context(context)
    assert "RESOURCE SUMMARY" in rendered


def test_named_service_question_pulls_that_services_metrics():
    state = AgentState(trigger_type="user_question", question="is payment over-provisioned?")
    context = build_context(state)
    assert context["mode"] == "service"
    assert context["service"] == "payment"
    assert context["metrics"]["memory"]["avg_pct"] is not None
    rendered = render_context(context)
    assert "payment metrics" in rendered


def test_trace_question_builds_span_tree_and_service_metrics():
    state = AgentState(trigger_type="user_question", trace_id=FIXTURE_TRACE_ID)
    context = build_context(state)
    assert context["mode"] == "trace"
    assert context["trace"] is not None
    services = {sp["service"] for sp in context["trace"]}
    assert "checkout" in services and "payment" in services
    assert "payment" in context["service_metrics"]
    rendered = render_context(context)
    assert FIXTURE_TRACE_ID in rendered


def test_format_service_row_labels_each_field_explicitly():
    # Real LLM-testing bug: two services with distinct error_rates got dumped as raw dicts
    # and deepseek-chat misattributed one service's error_rate to the other. Explicit
    # per-field labels next to the service name are the fix -- lock the format in.
    row = {
        "cpu": {"avg_pct": 1.0, "peak_pct": 2.0},
        "memory": {"avg_pct": 80.0, "peak_pct": 81.0, "used_bytes": 117411840, "limit_bytes": 146800640},
        "request_rate": 0.3,
        "p95_latency_ms": 12.5,
        "error_rate": 0.07,
    }
    rendered = _format_service_row("accounting", row)
    assert rendered.startswith("- accounting:")
    assert "error_rate=7.0%" in rendered
    assert "112MiB/140MiB" in rendered


def test_widen_on_retry_doubles_the_general_window():
    end_state = AgentState(trigger_type="user_question", question="how is the system doing?", loop_count=0)
    widened_state = AgentState(trigger_type="user_question", question="how is the system doing?", loop_count=1)
    base = build_context(end_state)
    widened = build_context(widened_state)
    base_span = base["window"]["end"] - base["window"]["start"]
    widened_span = widened["window"]["end"] - widened["window"]["start"]
    assert widened_span == base_span * 2
