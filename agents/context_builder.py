"""Pure Python context assembly for the analyst. No LLM calls here -- this is the layer
that keeps the analyst grounded (see docs/PHASE3.md 3.3): fetch the RIGHT real telemetry,
never let the LLM invent numbers it wasn't given."""
from __future__ import annotations

import re
import time

from retrieval.log_client import LogClient
from retrieval.metric_client import RESOURCE_SERVICES, MetricClient
from retrieval.trace_client import TraceClient

_BASE_GENERAL_WINDOW_S = 900  # 15 min, per PHASE3.md 3.5 default for a general question
_BASE_SERVICE_WINDOW_S = 1800  # 30 min, per PHASE3.md 3.3 default for a named-service question
_MAX_LOG_LINES = 40

_metrics = MetricClient()
_traces = TraceClient()
_logs = LogClient()


def _find_named_service(question: str | None) -> str | None:
    if not question:
        return None
    for service in RESOURCE_SERVICES:
        if re.search(rf"\b{re.escape(service)}\b", question, re.IGNORECASE):
            return service
    return None


def _flatten(node):
    yield node
    for child in node.children:
        yield from _flatten(child)


def _service_metrics(service: str, start: float, end: float) -> dict:
    p95 = _metrics.get_latency_p95(service, start, end)
    return {
        "cpu": _metrics.get_cpu_usage(service, start, end),
        "memory": _metrics.get_memory_usage(service, start, end),
        "request_rate": _metrics.get_request_rate(service, start, end),
        "error_rate": _metrics.get_error_rate(service, start, end),
        "p95_latency_ms": sum(p95) / len(p95) if p95 else None,
    }


def build_context(state) -> dict:
    """state: an AgentState (or anything with .trace_id/.question/.time_range/.signals/.loop_count)."""
    widen = 2**state.loop_count  # widen the window on each analyst retry (hard-capped at 2 by the orchestrator)
    context: dict = {"signals": state.signals}

    if state.trace_id:
        context.update(_trace_context(state.trace_id))
        return context

    named_service = _find_named_service(state.question)
    end = time.time()
    if state.time_range:
        start, end = float(state.time_range[0]), float(state.time_range[1])
    elif named_service:
        start = end - _BASE_SERVICE_WINDOW_S * widen
    else:
        start = end - _BASE_GENERAL_WINDOW_S * widen

    if named_service:
        context["mode"] = "service"
        context["service"] = named_service
        context["metrics"] = _service_metrics(named_service, start, end)
        context["logs"] = _render_logs(_logs.get_logs_by_time_range(start, end, service=named_service))
    else:
        context["mode"] = "general"
        context["resource_summary"] = _metrics.get_resource_summary(start, end)
        context["logs"] = _render_logs(
            _logs.get_logs_by_time_range(start, end, levels=["error", "warn"])
        )

    context["window"] = {"start": start, "end": end}
    return context


def _trace_context(trace_id: str) -> dict:
    root = _traces.get_trace(trace_id)
    context: dict = {"mode": "trace", "trace_id": trace_id}
    if root is None:
        context["trace"] = None
        return context

    spans = list(_flatten(root))
    context["trace"] = [
        {"service": n.service, "operation": n.operation, "duration_ms": round(n.duration_ms, 1), "status": n.status}
        for n in spans
    ]
    context["logs"] = _render_logs(_logs.get_logs_by_trace_id(trace_id))

    trace_start_s = root.start / 1e9
    window = (trace_start_s - 60, trace_start_s + max(60.0, root.duration_ms / 1000 + 60))
    context["service_metrics"] = {
        service: _service_metrics(service, *window) for service in {n.service for n in spans}
    }
    return context


def _render_logs(entries) -> list[dict]:
    return [{"service": e.service, "level": e.level, "message": e.message} for e in entries][-_MAX_LOG_LINES:]


def render_context(context: dict) -> str:
    """Turn the compact context dict into text for the analyst prompt."""
    lines = [f"Mode: {context.get('mode', 'general')}"]

    if context.get("signals"):
        lines.append("\nDETECTOR SIGNALS (measured, trusted facts):")
        for s in context["signals"]:
            lines.append(f"- {s}")

    if context.get("window"):
        w = context["window"]
        lines.append(f"\nWindow: {w['start']:.0f} to {w['end']:.0f} (unix seconds)")

    if "trace" in context:
        if context["trace"] is None:
            lines.append(f"\nTrace {context['trace_id']}: NOT FOUND in Tempo.")
        else:
            lines.append(f"\nTRACE {context['trace_id']} spans (in span-tree order):")
            for sp in context["trace"]:
                lines.append(f"- {sp['service']}.{sp['operation']} {sp['duration_ms']}ms status={sp['status']}")
            lines.append("\nSERVICE METRICS around the trace window:")
            for service, m in context.get("service_metrics", {}).items():
                lines.append(f"- {service}: {m}")

    if "resource_summary" in context:
        lines.append("\nRESOURCE SUMMARY (per service: cpu, memory, request_rate, error_rate, p95_latency_ms):")
        for row in context["resource_summary"]:
            lines.append(f"- {row}")

    if "metrics" in context:
        lines.append(f"\n{context['service']} metrics: {context['metrics']}")

    if context.get("logs"):
        lines.append(f"\nRECENT LOGS ({len(context['logs'])}):")
        for e in context["logs"]:
            lines.append(f"[{e['level']}] {e['service']}: {e['message'][:200]}")

    return "\n".join(lines)
