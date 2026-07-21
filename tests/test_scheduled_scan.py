"""Deterministic test for scripts/scheduled_scan.py's dedupe logic. No live infra, no LLM calls."""
from unittest.mock import MagicMock, patch

from detection.signal_detector import Signal
from scripts.scheduled_scan import scan_once

_CPU_AD = Signal(
    signal_type="cpu_high",
    confidence=0.9,
    affected_services=["ad"],
    metric_values={"avg_cpu_pct": 95.0},
    window=(0.0, 120.0),
)


def _detector(signals):
    d = MagicMock()
    d.detect.return_value = signals
    return d


@patch("scripts.scheduled_scan.run_orchestrator")
def test_first_sighting_fires(mock_run):
    last_fired = {}
    fresh = scan_once(_detector([_CPU_AD]), last_fired, now=1000.0)
    assert len(fresh) == 1
    assert mock_run.call_count == 1
    assert ("cpu_high", "ad") in last_fired


@patch("scripts.scheduled_scan.run_orchestrator")
def test_repeat_within_dedupe_window_is_suppressed(mock_run):
    last_fired = {("cpu_high", "ad"): 1000.0}
    fresh = scan_once(_detector([_CPU_AD]), last_fired, now=1000.0 + 299)
    assert fresh == []
    assert mock_run.call_count == 0


@patch("scripts.scheduled_scan.run_orchestrator")
def test_repeat_after_dedupe_window_fires_again(mock_run):
    last_fired = {("cpu_high", "ad"): 1000.0}
    fresh = scan_once(_detector([_CPU_AD]), last_fired, now=1000.0 + 301)
    assert len(fresh) == 1
    assert mock_run.call_count == 1
    assert last_fired[("cpu_high", "ad")] == 1000.0 + 301


@patch("scripts.scheduled_scan.run_orchestrator")
def test_no_signals_no_calls(mock_run):
    fresh = scan_once(_detector([]), {}, now=1000.0)
    assert fresh == []
    assert mock_run.call_count == 0


if __name__ == "__main__":
    import subprocess
    import sys

    sys.exit(subprocess.call(["python3", "-m", "pytest", __file__, "-v"]))
