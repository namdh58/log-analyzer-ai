"""Live end-to-end check (PHASE2.md Check 5): run each real chaos scenario against the
running demo stack and confirm SignalDetector.detect() fires the expected signal_type.
Slow (each scenario runs for real for SCENARIO_DURATION seconds) -- not part of the
default fast test suite; run explicitly with: pytest tests/test_detection_scenarios.py -v -s
"""
import time

import pytest

from chaos.scenarios import run as run_scenario
from detection.signal_detector import SignalDetector

SCENARIO_DURATION = 180  # long enough to reliably catch >=1 checkout/order in this env's
# low real traffic (~1.4 orders/min once the broken load-gen Playwright bots are excluded,
# see PROGRESS.md known issue) -- queue_backlog and payment_* need an actual order attempt
# to manifest at all.
POST_SCENARIO_BUFFER = 30  # let Prometheus/Tempo/Loki catch up on ingestion before querying

EXPECTED = {
    "payment_failure": {"error_rate_spike"},
    "payment_outage": {"span_gap", "error_rate_spike"},
    "queue_backlog": {"queue_anomaly"},
    "overload": {"latency_spike", "throughput_drop"},
}


@pytest.mark.parametrize("scenario", sorted(EXPECTED))
def test_scenario_fires_expected_signal(scenario):
    start = time.time()
    run_scenario(scenario, SCENARIO_DURATION)
    end = time.time()
    time.sleep(POST_SCENARIO_BUFFER)

    signals = SignalDetector().detect(start, end)
    fired_types = {s.signal_type for s in signals}
    print(f"\n{scenario}: fired={fired_types}")
    for s in signals:
        print(" ", s.signal_type, s.affected_services, round(s.confidence, 2), s.metric_values)

    expected_any_of = EXPECTED[scenario]
    assert fired_types & expected_any_of, (
        f"{scenario}: expected one of {expected_any_of}, got {fired_types}"
    )
