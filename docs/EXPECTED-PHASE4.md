# EXPECTED OUTPUT — Phase 4 (Chat Dashboard & Alerts)

Mostly visual — you look at the chat app and click. The chat app is the demo centerpiece, so its answers must look good, not just work.

---

## Check 1 — Chat app answers the example chips
**Do:** open http://localhost:8500, click each example chip.
**Expect:** each returns a readable answer card within ~60s: prose answer on top, findings color-coded by severity, recommendations with risk badges. Not raw JSON.
**If it's wrong:** spinner forever → `/ask` errored server-side (check FastAPI logs); confirm the analyst runs standalone first. Raw JSON shown → the UI isn't rendering the `answer` field, it's dumping the whole object.

## Check 2 — The flagship answer: right-sizing
**Ask:** "Is the payment service over-provisioned?"
**Expect:** real CPU/mem numbers vs limit + a clear verdict (over/under/appropriate) + a right-sizing recommendation. This is the answer that sells the demo — it should read like a competent SRE wrote it.
**If it's wrong:** no numbers or wrong numbers → context builder isn't feeding resource metrics (see Phase 3 Check 2). Cross-check the numbers against the live resource table / Grafana.

## Check 3 — Live resource table
**Do:** look at the resource utilization table on the dashboard (from `/resource-summary`).
**Expect:** real per-service CPU% and mem% updating, no LLM call needed. Lets viewers verify the AI isn't making numbers up.
**If it's wrong:** empty → `/resource-summary` endpoint or the PromQL behind it is broken (Phase 3 Check 1).

## Check 4 — Healthy-state answer
**Ask:** "How is the system doing right now?" on a quiet system.
**Expect:** healthy verdict, real supporting numbers, no invented problems.

## Check 5 — Alert banner → analysis
**Do:** run `adHighCpu`, wait, watch the dashboard.
**Expect:** an alert banner appears ("ad CPU high"); clicking it runs an analysis that explains the CPU exhaustion and recommends scaling. The whole alert→analyze→recommend loop visible in-app.
**If it's wrong:** no banner → `/alerts` endpoint not returning the detector signal, or `cpu_high` threshold not added (Phase 3 §3.6). 

## Check 6 — Grafana supporting panels
**Expect:** "AI Copilot" dashboard shows resource utilization + latency/error panels with real data, and "Recent AI analyses" lists results after you've asked a few questions.

## Check 7 (OPTIONAL) — Teams
Only if you set up a Workflows webhook. On a critical alert, expect a formatted Teams message (dashboard link as plain URL, not a button). Nothing arrives → likely a dead classic-connector URL (disabled May 2026); recreate via the Workflows app.

---
### Phase 4 is DONE when
Checks 1-5 look right on screen — especially Check 2 (right-sizing) and Check 5 (alert→analysis), the two moments that make the demo land. Grafana (6) is nice-to-have context. Teams (7) is a skip-without-guilt stretch. The must-have: click a chip → get a smart, grounded answer.
