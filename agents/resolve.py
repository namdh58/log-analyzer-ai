"""Bounded multi-turn reference resolution. Heuristic first (no LLM); one FAST-tier LLM
call only for vague follow-ups that need prior turns to make sense. Never raises -- always
falls back to the raw question so a resolve failure can't break the pipeline.

Memory is for REFERENCE RESOLUTION only. Numbers/facts always come from context_builder's
fresh telemetry fetch on the RESOLVED question, never from memory. See docs/PHASE4.md."""
from __future__ import annotations

import re

from agents.llm import complete
from retrieval.metric_client import RESOURCE_SERVICES

_TRACE_ID_RE = re.compile(r"\b[0-9a-f]{32}\b", re.IGNORECASE)
_VAGUE_RE = re.compile(
    r"\b(what about|which of (?:them|those)|compare (?:them|those)|the other one|thế còn)\b"
    r"|\b(it|its|that|those)\b",
    re.IGNORECASE,
)

_SYSTEM = (
    "Rewrite the user's follow-up question into a standalone, explicit question using the "
    "prior conversation for context. Output ONLY the rewritten question, nothing else."
)


def _named_service(question: str) -> str | None:
    for service in RESOURCE_SERVICES:
        if re.search(rf"\b{re.escape(service)}\b", question, re.IGNORECASE):
            return service
    return None


def needs_resolve(question: str, history: list[dict]) -> bool:
    """Skip (no LLM call) when there's no history, or the question is already
    self-contained: names a service, contains a trace_id, or has no vague reference."""
    if not history or not question:
        return False
    if _TRACE_ID_RE.search(question) or _named_service(question):
        return False
    return bool(_VAGUE_RE.search(question))


def render_memory(history: list[dict]) -> str:
    return "\n\n".join(f"Q: {t['question']}\nA: {t['answer_summary']}" for t in history[-4:])


def resolve(question: str, history: list[dict]) -> str:
    if not needs_resolve(question, history):
        print(f"[resolve] skip (self-contained or no history): {question!r}")
        return question
    user = f"Prior conversation:\n{render_memory(history)}\n\nFollow-up: {question}"
    try:
        rewritten = complete(_SYSTEM, user, model_tier="fast")
        rewritten = rewritten.strip() if isinstance(rewritten, str) else ""
    except Exception as e:
        print(f"[resolve] LLM call failed ({e}), falling back to raw question")
        return question
    if len(rewritten) < 5:
        print(f"[resolve] empty/nonsensical rewrite, falling back to raw question: {question!r}")
        return question
    print(f"[resolve] {question!r} -> {rewritten!r}")
    return rewritten
