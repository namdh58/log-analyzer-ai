"""Background scanner: detect() every 60s over the last ~2min window, trigger the
orchestrator (as an alert) on any new signal, dedup by signal_type+service within 5min.
See docs/PHASE5.md 5.1. Run: python -m scripts.scheduled_scan
"""
import time

from agents.orchestrator import run as run_orchestrator
from agents.schemas import AgentState
from detection.signal_detector import Signal, SignalDetector

_POLL_INTERVAL_S = 60
_WINDOW_S = 120
_DEDUPE_S = 300


def _key(s: Signal) -> tuple[str, str]:
    return (s.signal_type, ",".join(sorted(s.affected_services)))


def _alert_question(s: Signal) -> str:
    svc = ", ".join(s.affected_services)
    return f"Signal detected: {s.signal_type.replace('_', ' ')} on {svc}. What's happening and what should I do?"


def scan_once(detector: SignalDetector, last_fired: dict[tuple[str, str], float], now: float) -> list[Signal]:
    """One detect pass; returns signals that were NOT deduped (and triggers the orchestrator for each)."""
    signals = detector.detect(now - _WINDOW_S, now)
    fresh = []
    for s in signals:
        key = _key(s)
        fired_at = last_fired.get(key)
        if fired_at is not None and now - fired_at < _DEDUPE_S:
            continue
        last_fired[key] = now
        fresh.append(s)
        run_orchestrator(
            AgentState(
                trigger_type="alert",
                question=_alert_question(s),
                signals=[s.model_dump()],
                time_range=(str(now - _WINDOW_S), str(now)),
            )
        )
    return fresh


def main() -> None:
    detector = SignalDetector()
    last_fired: dict[tuple[str, str], float] = {}
    print(f"scheduled_scan: polling every {_POLL_INTERVAL_S}s, window={_WINDOW_S}s, dedupe={_DEDUPE_S}s")
    while True:
        now = time.time()
        fresh = scan_once(detector, last_fired, now)
        if fresh:
            print(f"[{time.strftime('%H:%M:%S')}] fired {len(fresh)} signal(s): {[_key(s) for s in fresh]}")
        time.sleep(_POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
