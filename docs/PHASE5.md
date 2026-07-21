# PHASE 5 — Integration, Demo Script, Smoke Tests (Day 3 pm)

Read CLAUDE.md + PROGRESS.md first. Depends on Phases 1-4. Goal: a smooth, deterministic demo that shows the copilot answering real infrastructure questions — failures AND performance/right-sizing/capacity — plus tests that confirm it works.

## 5.1 Scheduled scanner (`scripts/scheduled_scan.py`)
- Loop every 60s: run detector (`detect()`) on the last ~2-min window (error/latency/queue/throughput + the new cpu_high/memory_high).
- Signal found → trigger Orchestrator (`trigger_type="scheduled"`, treated as alert) → analysis persisted + alert available to the dashboard banner. No signal → zero LLM calls.
- Dedupe: don't re-fire the same signal_type+service within 5 min.

## 5.2 Demo runner (`scripts/run_demo.py`)
Presenter-paced, deterministic. The demo tells a story: "an AI copilot that understands your running system." Structure it as a sequence of QUESTIONS (the compelling part), with one live failure injection in the middle.

```
=== Distributed Observability AI Copilot — DEMO ===
[health] Loki / Prometheus / Tempo / Grafana / shop  → all OK

--- Act 1: Everyday questions (system is healthy) ---
Q: "How is the system doing right now?"
   → analyst: healthy verdict + real numbers
[Enter]
Q: "Is the payment service over-provisioned?"
   → analyst: real CPU/mem vs limit + right-sizing verdict + est. savings framing
[Enter]
Q: "If traffic tripled, which service saturates first?"
   → analyst: headroom analysis, names the tightest service
[Enter]

--- Act 2: Something goes wrong (live injection) ---
[chaos] enable adHighCpu (run ~90s)
[wait] ingesting... 15s
[alert] cpu_high fired on ad service
Q: (auto) "The ad service just alerted — what's happening and what should I do?"
   → analyst: explains CPU exhaustion, recommends scale up/out, cites numbers
[chaos] reset flag
[Enter]

--- Act 3: Failure investigation ---
[chaos] enable paymentFailure (run ~60s), capture a failing trace_id
Q: "What's wrong with checkout right now?" (or ask about the trace_id)
   → analyst: explains payment failures, fix recommendation
[chaos] reset flag
[cost] total LLM calls / tokens for the demo
=== DEMO COMPLETE ===
```
- Flags: `--act 1|2|3` to run one act; `--provider ollama` passthrough. Reset all flags on exit (and on Ctrl+C).
- This ordering leads with breadth (health, right-sizing, capacity) — the differentiator — then shows it handles real failures too.

## 5.3 Smoke tests (`tests/test_e2e_scenario.py`)
Pytest, `@pytest.mark.e2e`. Cover the capabilities, not just the 4 failures:
```
test_healthy_state_reported()      # quiet system → answer mentions healthy + no invented problem
test_rightsizing_answer()          # "is payment over-provisioned" → answer contains real cpu/mem numbers + a verdict
test_cpu_alert_and_recommend()     # adHighCpu → cpu_high signal + answer recommends scaling
test_payment_failure_explained()   # paymentFailure → answer identifies payment as failing
test_schema_valid_and_grounded()   # every answer is valid AnalystAnswer with non-empty evidence
```
Grounding assertion tip: assert that numbers in the answer/evidence actually appear in the fetched telemetry (guards against hallucination) — even a loose check (evidence list non-empty AND references a real service name) catches the worst failure mode. Soft-fail LLM-judgment cases (log the full answer), hard-fail only crashes.

## 5.4 Pre-demo checklist
- [ ] `docker compose down -v && up -d`; let the load generator build ~15 min of baseline before demoing (right-sizing answers need real utilization history).
- [ ] Dry-run `run_demo.py` once; time each act (watch for dead air on the ~60s LLM calls — consider pre-warming or trimming).
- [ ] All flags reset off.
- [ ] Chat app + Grafana pre-opened; resource table populated.
- [ ] Prepared answer for "does it hallucinate?": show that evidence quotes real Prometheus numbers, and the live resource table lets anyone cross-check.
- [ ] Prepared answer for "production cost?": fast tier for light tasks, smart tier only for analysis, zero LLM calls when nothing's asked/quiet scans, plus optional fully-local Ollama mode as the zero-API-cost story.

## Acceptance criteria (project done)
- [ ] `run_demo.py` runs all 3 acts cleanly, in order, readable, flags reset.
- [ ] ≥4 of 5 smoke tests pass (document any flaky one).
- [ ] Chat app answers the four example chips convincingly on a live system.
- [ ] Right-sizing + healthy-state answers quote REAL numbers (spot-check against Grafana).
- [ ] Dashboard shows recent analyses + live resource table afterward.
- [ ] PROGRESS.md final summary lists all deviations from the original plan.
