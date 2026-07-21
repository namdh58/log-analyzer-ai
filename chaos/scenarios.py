"""Run a named chaos scenario end-to-end: enable flag, wait, disable flag, log the event.

Usage: python -m chaos.scenarios <name> [--duration 120]
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from chaos.flags import install_signal_handlers, reset_all, set_flag

LOG_PATH = Path(__file__).parent / "injected_events.log"

# name -> (flagd flag, variant). Flag names verified against otel-demo/src/flagd/demo.flagd.json.
SCENARIOS = {
    "payment_failure": ("paymentFailure", "100%"),
    "payment_outage": ("paymentUnreachable", "on"),
    "queue_backlog": ("kafkaQueueProblems", "on"),
    "overload": ("adHighCpu", "on"),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(scenario: str, duration: int) -> None:
    flag, variant = SCENARIOS[scenario]
    install_signal_handlers()
    start = _now_iso()
    print(f"[{start}] enabling {flag}={variant} for {duration}s ({scenario})")
    set_flag(flag, variant)
    try:
        time.sleep(duration)
    finally:
        reset_all()
        end = _now_iso()
        print(f"[{end}] reset flags")
        with LOG_PATH.open("a") as f:
            f.write(json.dumps({"scenario": scenario, "flag": flag, "start": start, "end": end}) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=sorted(SCENARIOS))
    parser.add_argument("--duration", type=int, default=120)
    args = parser.parse_args()
    run(args.scenario, args.duration)
