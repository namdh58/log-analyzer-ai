"""Shared Pydantic models for the retrieval layer."""
from __future__ import annotations

from pydantic import BaseModel


class LogEntry(BaseModel):
    timestamp: int  # unix nanoseconds
    service: str
    level: str
    message: str
    trace_id: str = ""
    span_id: str = ""
    raw: str = ""


class SpanNode(BaseModel):
    trace_id: str
    span_id: str
    parent_span_id: str = ""
    service: str
    operation: str
    start: int  # unix nanoseconds
    duration_ms: float
    status: str
    children: list["SpanNode"] = []
