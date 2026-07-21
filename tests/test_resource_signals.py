"""Deterministic-ish live check for the Phase 3 resource-based detector signals
(PHASE3.md 3.6). No chaos scenario needed for memory_high -- `ad`/`fraud-detection`
genuinely sit pinned near their 300MiB memory limit continuously in this env (see
PROGRESS.md known issue), so it's a real, always-available fixture for this check.
"""
import time

from detection.signal_detector import SignalDetector


def test_memory_high_fires_on_chronically_pinned_service():
    end = time.time()
    start = end - 900
    signals = SignalDetector().detect(start, end)
    memory_signals = {s.affected_services[0]: s for s in signals if s.signal_type == "memory_high"}
    assert "ad" in memory_signals, f"expected memory_high on `ad`, got signals: {[s.signal_type for s in signals]}"
    sig = memory_signals["ad"]
    assert sig.metric_values["avg_memory_pct"] > 90
    assert sig.metric_values["limit_bytes"] == 314572800
