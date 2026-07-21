# EXPECTED OUTPUT — Phase 4 (Dashboard & Chat)

Mostly visual verification — you look at screens. Teams is optional, verify only if you set it up.

---

## Check 1 — Grafana panels show real data
**Do:** open the "AI Copilot Overview" dashboard in Grafana.
**Expect:**
- Error timeline panel: shows ERROR counts by service; spikes appear where you ran chaos.
- Latency/error-rate panel: p95 latency + error rate lines per service, moving over time.
- "Recent RCA results" panel (Loki, `service="ai-copilot"`): after you've run a pipeline, at least one readable entry showing anomaly_type + hypothesis.
**If it's wrong:**
- Panels empty → wrong datasource UID in the dashboard JSON, or query references a label/metric that doesn't exist (reuse the exact names from PROGRESS.md).
- RCA panel empty but pipeline ran → the persist node isn't pushing to Loki with `service="ai-copilot"`, or the label filter in the panel doesn't match.

## Check 2 — Chat app answers about a trace
**Do:** open http://localhost:8500 → ask `anything abnormal in trace <a real trace_id from a chaos run>?`
**Expect:** a visible "analyzing…" state, then within ~30-90s an answer card showing: hypothesis, confidence, evidence list, recommendation, references. Not raw JSON dumped as text — formatted readable.
**If it's wrong:**
- Spinner forever → `/ask` errored server-side (check FastAPI logs); or the request timed out. Confirm Orchestrator runs standalone first.
- Returns but can't find the trace → `user_question` trace_id parsing failed. Test the regex on the actual question string.

## Check 3 — Chat app answers about a time window
**Do:** ask `what happened in the last 10 minutes?` (right after a chaos run).
**Expect:** it resolves to a time_range, runs detect + pipeline, returns a relevant answer. If nothing was wrong in that window, it should say so — not hallucinate a problem.
**If it's wrong:** always finds a problem even in quiet windows → it's skipping the signal-detector gate and running the LLM regardless. The `scheduled`/`user_question` path must check signals first.

## Check 4 — History endpoint
**Do:** `GET http://localhost:8500/history` (or the history list in the UI).
**Expect:** last ~20 pipeline results from `results/rca_history.jsonl`, newest first.

## Check 5 (OPTIONAL) — Teams
Only if you set up a Workflows webhook. Run a chaos scenario, let the pipeline finish.
**Expect:** a Teams message with anomaly_type in the title, service + confidence facts, hypothesis + recommendation text, dashboard link as plain URL (not a button — buttons don't render on MessageCard via Workflows).
**If it's wrong:** nothing arrives → the webhook URL is a dead classic-connector URL (those were disabled May 2026); recreate via the Workflows app. Or the send condition (severity critical OR confidence>0.7) wasn't met — check the result values.

---
### Phase 4 is DONE when
Checks 1-4 look right on screen. Check 5 only if you chose to do Teams (it's a stretch — skip without guilt if short on time). The must-have is: chat box → ask about a trace → readable answer. That's the demo centerpiece.
