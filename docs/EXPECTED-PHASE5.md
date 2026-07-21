# EXPECTED OUTPUT — Phase 5 (Integration, Demo, Smoke Tests)

This is the "does the whole thing hang together" phase. Output = a clean demo run + a test report.

---

## Check 1 — Scheduled scanner behaves
**Run:** `python scripts/scheduled_scan.py` with NO chaos active, watch for a minute.
**Expect:** it scans every 60s, finds no signals, makes ZERO LLM calls (you'll see no cost lines). Then trigger a chaos scenario → next scan finds a signal → fires the pipeline once (not repeatedly for the same thing within 5 min).
**If it's wrong:**
- LLM calls during quiet time → the "no signal = no LLM" gate is broken (costs money for nothing).
- Fires same alert every 60s → dedupe missing.

## Check 2 — Demo runner: the money shot
**Run:** `python scripts/run_demo.py`
**Expect this exact flow, per scenario, readable in the terminal:**
```
=== Distributed Observability AI Copilot — DEMO ===
[health] Loki OK | Prometheus OK | Tempo OK | Grafana OK | Shop OK

--- Scenario 1/4: payment_failure ---
[chaos] flag paymentFailure = 100%  (running 90s)... done, flag reset
[wait] ingesting telemetry... 15s
[detect] signals: error_rate_spike (payment, conf 0.9)
[extract] service=payment error_type=charge_failed severity=critical
[rca] anomaly_type=service_failure confidence=0.82
       "Payment service is rejecting charge requests..."
[fix] risk=medium  "Add circuit breaker + retry with backoff..."  refs: [...]
[persist] written to rca_history.jsonl + Loki
[cost] LLM calls: 3 | in: 4200 tok | out: 610 tok
>>> Press Enter for next scenario...
```
Then scenarios 2-4, then `=== DEMO COMPLETE ===`.
**If it's wrong:**
- Health check fails → stack not fully up; fix before anything else.
- A scenario hangs → likely the pipeline waiting on an LLM call or a dead infra query; the health check should have caught infra.
- Stops mid-way → run with `--scenario <name>` to isolate which one breaks.

## Check 3 — Smoke test report
**Run:** `pytest tests/test_e2e_scenario.py -m e2e`
**Expect:** a summary like:
```
payment_failure  → service_failure     ✓
queue_backlog    → message_loss        ✓
payment_outage   → broken_trace        ✓
overload         → resource_exhaustion ✗ (got: timeout)   [soft-fail, logged]
3/4 passed
```
≥3/4 is a pass for this project. Soft-fails are logged, not crashes.
**If it's wrong:** hard crash (not an assertion diff) → a real bug, not LLM judgment. Fix it. Assertion diff on one scenario → acceptable, note it; try one threshold/prompt tweak, don't rabbit-hole.

## Check 4 — Dashboard shows the aftermath
**Do:** after the demo run, open Grafana + chat app.
**Expect:** all 4 results visible in the RCA panel; chat can answer about any trace_id you just demoed.

## Check 5 — Clean-environment reproducibility
**Run:** `docker compose down -v && docker compose up -d`, wait ~15 min for baseline traffic, then `run_demo.py` again.
**Expect:** same clean run. This proves it's not held together by leftover state — critical before demoing live.

---
### Project is DONE when
- `run_demo.py` completes all 4 scenarios cleanly, in order, readable.
- ≥3/4 smoke tests pass.
- Dashboard + chat work on just-demoed data.
- PROGRESS.md final summary lists every deviation from the original plan.

### Pre-demo dry-run (do this the morning of, on clean env)
Time each scenario during the dry run. If any scenario's detect+pipeline takes >2 min, that's your dead-air risk — pre-run those flags a bit earlier, or trim `--duration`. A demo that works but makes people wait 3 minutes staring at a spinner still feels broken. Rehearse the pacing.
