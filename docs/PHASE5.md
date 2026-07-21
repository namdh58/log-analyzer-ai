# PHASE 5 — End-to-End Integration, Demo Script, Smoke Tests (Day 3 pm)

Read CLAUDE.md + PROGRESS.md first. Depends on Phases 1-4.

## 5.1 Scheduled scanner (`scripts/scheduled_scan.py`)
- Loop every 60s (`time.sleep` is fine): `SignalDetector.detect()` on the last 2-minute window.
- Signals found → trigger Orchestrator with `trigger_type="scheduled"` (this doubles as the "alert" path — no separate Alertmanager). No signals → zero LLM calls.
- Dedupe: don't re-trigger for the same signal_type+service within 5 minutes.

## 5.2 Demo runner (`scripts/run_demo.py`)
Deterministic, presenter-paced. For each of the 4 scenarios (payment_failure, queue_backlog, payment_outage, overload):
```
1. Health-check Loki/Prometheus/Tempo/Grafana/shop (fail fast with clear message).
2. Print scenario banner → run chaos scenario (duration ~90-120s so signals are measurable).
3. Wait for ingestion (~15s after flag off), print countdown.
4. Trigger Orchestrator directly on the scenario's time window (do not wait for scheduled scan).
5. Pretty-print each stage: signals → extraction → RCA → fix → "persisted to dashboard/Loki" (+ Teams if enabled). Print LLM call/token counts.
6. Wait for Enter before next scenario (presenter controls pacing).
```
Add `--scenario <name>` to run just one, and `--provider ollama` passthrough.

## 5.3 Smoke tests (`tests/test_e2e_scenario.py`)
4 pytest cases, one per scenario: run chaos → run pipeline → assert:
- payment_failure: `anomaly_type == "service_failure"`, confidence > 0.5
- queue_backlog: `== "message_loss"`
- payment_outage: `in ["broken_trace","timeout"]`
- overload: `in ["resource_exhaustion","timeout"]`
Mark tests `@pytest.mark.e2e` (slow, cost money). If an assert fails due to LLM judgment (not a crash), log the full output for prompt/threshold tuning instead of hard-failing the whole suite (use soft-assert + summary report).

## 5.4 Pre-demo checklist
- [ ] `docker compose down -v && up -d`, wait for load generator to build ~15 min of baseline before demoing.
- [ ] Full `run_demo.py` dry-run once; note timing per scenario.
- [ ] All flagd flags reset to off before starting.
- [ ] Grafana tab pre-opened on the AI Copilot dashboard, correct time range; chat app pre-opened.
- [ ] If Teams enabled: send a test message beforehand.
- [ ] Prepared answer for "what would this cost in production?": fast tier (Haiku) for extraction, smart tier (Sonnet) only for RCA/fix, zero LLM calls in quiet windows, hard loop cap — plus optional fully-local mode (Ollama) as the zero-API-cost story.

## Acceptance criteria (project done)
- [ ] ≥3 of 4 smoke tests pass (document any flaky case).
- [ ] `run_demo.py` completes all 4 scenarios cleanly in order.
- [ ] Dashboard shows all 4 results afterward; chat answers correctly about a just-demoed trace/window.
- [ ] Repo has final PROGRESS.md summarizing all deviations from the original plan.
