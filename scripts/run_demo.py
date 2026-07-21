"""Presenter-paced demo runner. See docs/PHASE5.md 5.2.

Usage:
    python -m scripts.run_demo                 # all 3 acts, paced with [Enter] prompts
    python -m scripts.run_demo --act 2          # just act 2
    python -m scripts.run_demo --provider ollama --no-pause   # unattended dry-run
"""
import argparse
import os
import signal
import sys
import time

_HEALTH_ENDPOINTS = [
    ("Loki", "http://localhost:3100/ready"),
    ("Prometheus", "http://localhost:9090/-/healthy"),
    ("Tempo", "http://localhost:3200/ready"),
    ("Grafana", "http://localhost:3000/api/health"),
    ("shop", "http://localhost:8080/"),
]


def _check_health() -> bool:
    import requests

    ok = True
    for name, url in _HEALTH_ENDPOINTS:
        try:
            requests.get(url, timeout=5)  # reachable at all == up; single-binary Loki/Tempo
        except requests.RequestException:  # cycle through transient 503 "not ready" blips
            ok = False
            print(f"  {name}: UNREACHABLE ({url})")
    names = " / ".join(n for n, _ in _HEALTH_ENDPOINTS)
    print(f"[health] {names}  -> {'all OK' if ok else 'SOME DOWN, see above'}")
    return ok


def _pause(no_pause: bool) -> None:
    if not no_pause:
        input("[Enter] ")


def _ask(question: str, conversation_id: str | None = None) -> None:
    from agents.orchestrator import run as run_orchestrator
    from agents.schemas import AgentState

    print(f"\nQ: {question!r}")
    state = run_orchestrator(
        AgentState(trigger_type="user_question", question=question, conversation_id=conversation_id)
    )
    print(f"   -> {state.answer.answer}")
    for f in state.answer.findings:
        print(f"      [{f.severity}] {f.summary}")
    for r in state.answer.recommendations:
        print(f"      recommend ({r.risk_level}): {r.action}")


def act1() -> None:
    print("\n--- Act 1: Everyday questions (system is healthy) ---")
    _ask("How is the system doing right now?")
    _pause(_NO_PAUSE)
    _ask("Is the payment service over-provisioned?")
    _pause(_NO_PAUSE)
    _ask("If traffic tripled, which service saturates first?")
    _pause(_NO_PAUSE)


def act2() -> None:
    from chaos.flags import reset_all, set_flag
    from detection.signal_detector import SignalDetector

    print("\n--- Act 2: Something goes wrong (live injection) ---")
    duration = 90
    print(f"[chaos] enable adHighCpu (run ~{duration}s)")
    start = time.time()
    set_flag("adHighCpu", "on")
    try:
        time.sleep(duration)
        print("[wait] ingesting... 15s")
        time.sleep(15)
        end = time.time()
        signals = SignalDetector().detect(start, end)
        cpu_signals = [s for s in signals if s.signal_type == "cpu_high" and "ad" in s.affected_services]
        if cpu_signals:
            pct = cpu_signals[0].metric_values.get("avg_cpu_pct", 0)
            print(f"[alert] cpu_high fired on ad service (avg {pct:.0f}%)")
        else:
            print("[alert] cpu_high did not cross threshold yet in this window (proceeding anyway)")
        _ask("The ad service just alerted -- what's happening and what should I do?")
    finally:
        reset_all()
        print("[chaos] reset flag")
    _pause(_NO_PAUSE)


def act3() -> None:
    from chaos.flags import reset_all, set_flag
    from detection.signal_detector import SignalDetector

    print("\n--- Act 3: Failure investigation ---")
    # PHASE5.md's sketch says ~60s, but real checkout traffic here is only ~1.4 orders/min
    # (see PROGRESS.md verified facts) -- 60s often sees zero checkout requests at all, so
    # there's nothing for the HTTP-error-rate check to fire on. 180s reliably catches one.
    duration = 180
    print(f"[chaos] enable paymentFailure (run ~{duration}s)")
    start = time.time()
    set_flag("paymentFailure", "100%")
    try:
        time.sleep(duration)
        end = time.time()
        signals = SignalDetector().detect(start, end)
        payment_signals = [s for s in signals if "payment" in s.affected_services]
        trace_id = None
        if payment_signals and payment_signals[0].affected_trace_ids:
            trace_id = payment_signals[0].affected_trace_ids[0]
            print(f"[capture] failing trace_id: {trace_id}")
        _ask("What's wrong with checkout right now?")
    finally:
        reset_all()
        print("[chaos] reset flag")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--act", type=int, choices=[1, 2, 3], default=None, help="run only this act")
    parser.add_argument("--provider", choices=["anthropic", "deepseek", "ollama"], default=None)
    parser.add_argument("--no-pause", action="store_true", help="skip [Enter] prompts (unattended dry-run)")
    args = parser.parse_args()

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider

    global _NO_PAUSE
    _NO_PAUSE = args.no_pause

    from chaos.flags import install_signal_handlers, reset_all

    install_signal_handlers()  # Ctrl+C mid-act still resets flags

    print("=== Distributed Observability AI Copilot -- DEMO ===")
    if not _check_health():
        print("warning: some services unreachable, continuing anyway")

    try:
        if args.act in (None, 1):
            act1()
        if args.act in (None, 2):
            act2()
        if args.act in (None, 3):
            act3()
    finally:
        reset_all()

    from agents.llm import usage

    print(f"\n[cost] {usage}")
    print("=== DEMO COMPLETE ===")


_NO_PAUSE = False

if __name__ == "__main__":
    main()
