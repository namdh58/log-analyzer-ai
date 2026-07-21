"""End-to-end smoke tests (PHASE5.md 5.3) against the live running stack.

Covers the capabilities, not just the 4 chaos failures -- healthy-state, right-sizing,
capacity, and failure-explanation questions, plus a grounding check. Per CLAUDE.md: no
hard-assert self-fixing on LLM judgment -- print the full answer for human review and
only hard-fail on crashes / missing evidence / schema violations, not on phrasing.

Not part of the default fast suite (each chaos test injects a real scenario and sleeps
180s+30s). Run explicitly: pytest tests/test_e2e_scenario.py -v -s -m e2e
"""
import time

import pytest

from agents.orchestrator import run as run_orchestrator
from agents.schemas import AgentState
from chaos.flags import reset_all, set_flag
from detection.signal_detector import SignalDetector
from retrieval.metric_client import RESOURCE_SERVICES

pytestmark = pytest.mark.e2e

# Real checkout traffic here is only ~1.4 orders/min (see PROGRESS.md verified facts) --
# 180s is the duration this project already established as reliably catching >=1 order
# (see tests/test_detection_scenarios.py).
SCENARIO_DURATION = 180
POST_BUFFER = 15


def _ask(question: str):
    answer = run_orchestrator(AgentState(trigger_type="user_question", question=question)).answer
    print(f"\nQ: {question!r}\nANSWER: {answer.answer}")
    return answer


def test_healthy_state_reported():
    answer = _ask("How is the system doing right now?")
    assert answer.answer.strip()
    assert answer.findings or "healthy" in answer.answer.lower()


def test_rightsizing_answer():
    answer = _ask("Is the payment service over-provisioned?")
    text = answer.answer.lower()
    assert "cpu" in text or "mem" in text
    assert any(ch.isdigit() for ch in answer.answer), "expected a real number quoted in the answer"


def test_cpu_alert_and_recommend():
    set_flag("adHighCpu", "on")
    try:
        time.sleep(SCENARIO_DURATION)
        end = time.time()
        signals = SignalDetector().detect(end - SCENARIO_DURATION, end)
        assert any(s.signal_type == "cpu_high" for s in signals), "expected cpu_high to fire during adHighCpu"
        answer = _ask("The ad service just alerted -- what's happening and what should I do?")
        assert answer.recommendations, "expected at least one recommendation"
    finally:
        reset_all()
        time.sleep(POST_BUFFER)


def test_payment_failure_explained():
    set_flag("paymentFailure", "100%")
    try:
        time.sleep(SCENARIO_DURATION)
        answer = _ask("What's wrong with checkout right now?")
        text = answer.answer.lower()
        assert "payment" in text or "checkout" in text or "500" in text
    finally:
        reset_all()
        time.sleep(POST_BUFFER)


def test_schema_valid_and_grounded():
    answer = _ask("Is the payment service over-provisioned?")
    assert answer.findings, "expected at least one finding"
    assert all(f.evidence for f in answer.findings), "every finding should cite evidence"
    referenced = {f.service for f in answer.findings if f.service}
    assert referenced & set(RESOURCE_SERVICES), f"no real service referenced in findings: {referenced}"
