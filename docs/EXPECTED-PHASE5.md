# EXPECTED OUTPUT — Phase 5 (Integration, Demo, Smoke Tests)

Output = a clean 3-act demo run + a passing test report. The demo should feel like "an AI that understands our running system," not "a script that detects 4 bugs."

---

## Check 1 — Scheduled scanner behaves
**Run:** `python scripts/scheduled_scan.py`, quiet system, watch a minute.
**Expect:** scans every 60s, no signals → ZERO LLM calls (no cost lines). Trigger a scenario → next scan fires one analysis (not repeatedly within 5 min).
**If it's wrong:** LLM calls during quiet time → the "no signal = no LLM" gate is broken. Same alert every 60s → dedupe missing.

## Check 2 — Demo runner: the 3-act flow
**Run:** `python scripts/run_demo.py`
**Expect this readable flow:**
```
[health] all OK
--- Act 1: healthy-system questions ---
  "How is the system doing?"          → healthy + numbers
  "Is payment over-provisioned?"      → real cpu/mem + verdict
  "Which service saturates first?"    → headroom analysis
--- Act 2: live failure ---
  [chaos adHighCpu] → [alert cpu_high] → analyst explains + recommends scale
--- Act 3: failure investigation ---
  [chaos paymentFailure] → "what's wrong with checkout?" → explains + fixes
[cost] total LLM calls / tokens
=== DEMO COMPLETE ===
```
Each analyst answer readable, grounded in numbers, flags reset between acts.
**If it's wrong:** health check fails → stack not up. An act hangs → LLM call stalled or infra query dead. Isolate with `--act N`.

## Check 3 — Smoke test report
**Run:** `pytest tests/test_e2e_scenario.py -m e2e`
**Expect:**
```
test_healthy_state_reported        ✓
test_rightsizing_answer            ✓
test_cpu_alert_and_recommend       ✓
test_payment_failure_explained     ✓
test_schema_valid_and_grounded     ✓
5/5 passed
```
≥4/5 is a pass. Soft-fails logged with the full answer for tuning; only crashes hard-fail.
**If it's wrong:** hard crash = real bug, fix it. Grounding assertion fails (numbers in answer not found in telemetry) = the analyst hallucinated → fix the context builder to feed real data, don't loosen the assertion blindly.

## Check 4 — Dashboard aftermath
**Do:** after the demo, open the chat app + Grafana.
**Expect:** recent analyses listed, live resource table populated, can still ask about any service/trace from the demo.

## Check 5 — Clean-environment reproducibility
**Run:** `docker compose down -v && up -d`, wait ~15 min for baseline, then `run_demo.py` again.
**Expect:** same clean run. Right-sizing answers need the baseline history, so don't skip the wait.

---
### Project is DONE when
- `run_demo.py` runs all 3 acts cleanly.
- ≥4/5 smoke tests pass.
- The four example chips answer convincingly live, quoting real numbers.
- PROGRESS.md final summary lists all deviations from the original plan.

### Pre-demo dry-run (morning of)
Time each act. The ~60s LLM analysis calls are your dead-air risk — rehearse talking over them ("while it reads the metrics, notice the live resource table it's reasoning from..."). A grounded answer that arrives after a narrated 40s beats a fast answer nobody trusts.
