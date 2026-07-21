"""Pydantic v2 schemas exchanged between agents. See docs/PHASE3.md 3.2."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class Finding(BaseModel):
    """One structured observation the analyst extracted from telemetry."""

    category: Literal["error", "performance", "resource", "capacity", "healthy"]
    service: Optional[str] = None
    summary: str
    evidence: list[str]
    severity: Literal["critical", "warning", "info"]


class Recommendation(BaseModel):
    action: str
    rationale: str
    risk_level: Literal["low", "medium", "high"]
    references: list[str] = []


class AnalystAnswer(BaseModel):
    """The complete answer to a question or alert."""

    answer: str
    findings: list[Finding] = []
    recommendations: list[Recommendation] = []
    services_examined: list[str] = []
    requires_human_review: bool = True


class AgentState(BaseModel):
    trigger_type: Literal["alert", "scheduled", "user_question"]
    question: Optional[str] = None
    trace_id: Optional[str] = None
    time_range: Optional[tuple[str, str]] = None
    signals: list[dict] = []
    context: dict = {}
    answer: Optional[AnalystAnswer] = None
    loop_count: int = 0
    # Bounded multi-turn (Phase 4 enhancement). Orchestration state only -- never part of
    # AnalystAnswer, so Phase 5's schema contract is unaffected.
    conversation_id: Optional[str] = None
    history: list[dict] = []  # last-N {question, answer_summary}, reference only
    resolved_question: Optional[str] = None
