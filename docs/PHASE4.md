# PHASE 4 — Chat Dashboard & Alerts (Day 3 am)

Read CLAUDE.md + PROGRESS.md first. Depends on Phase 3. The **chat interface is the demo centerpiece** — this is where judges see the AI answer real questions about the system. Grafana is supporting context; Teams is an optional stretch.

## 4.1 Chat web app (`interfaces/dashboard/`) — PRIMARY deliverable
- `app.py`: FastAPI on port 8500.
  - `POST /ask {question}` → Orchestrator with `trigger_type="user_question"` → returns the `AnalystAnswer` (answer text + findings + recommendations). May take 20-60s; simple long request is fine, add SSE/polling only if time permits.
  - `GET /history` → last 20 entries from `results/analysis_history.jsonl`.
  - `GET /resource-summary` → live `get_resource_summary()` so the UI can show a current utilization table without an LLM call (cheap, instant, good for demo).
  - `GET /` → serves static/index.html.
- `static/index.html`: vanilla JS, no build tools. Layout:
  - A prominent chat box with a few **example question chips** the presenter can click during the demo:
    - "How is the system doing right now?"
    - "Is payment over-provisioned?"
    - "Which service will saturate first if traffic triples?"
    - "What's wrong with the ad service?"
  - Answer area rendering the analyst response as a readable card: the `answer` prose up top, then findings (color-coded by severity) and recommendations (with risk_level badge + references).
  - A live resource-utilization table (from `/resource-summary`) so viewers see the real numbers the AI is reasoning over.
  - History list below.
  - Show a visible "analyzing…" state while `/ask` runs. Clean dark theme.
- The example chips matter: they make the demo smooth and let judges see breadth (health, right-sizing, capacity, failure) in four clicks.

## 4.2 Grafana panels (supporting context, keep light)
Add one provisioned dashboard "AI Copilot" (`overrides/grafana/dashboards/`):
- Resource utilization: CPU% and memory% per service (Prometheus) — this visually backs the analyst's right-sizing answers.
- Latency + error rate per service.
- "Recent AI analyses" (Loki panel, `service="ai-copilot"`) — the persist node already writes here; format so the answer summary is readable.
Don't over-invest — the chat app is the star. These panels exist so a judge can cross-check the AI's numbers against the source.

## 4.3 Alerts — in-app first, Teams optional
- **In-app alert banner (do this):** a `GET /alerts` endpoint returns any active detector signals (including the new `cpu_high`/`memory_high`). The dashboard polls it and shows a banner "⚠ ad service CPU at 92% — click to analyze", which fires `/ask` with a pre-filled question. This demonstrates the alert→analysis→recommendation flow entirely in-app, no external dependency.
- **Teams (OPTIONAL stretch, do LAST, skip if behind):** classic Office 365 connector webhooks were disabled by Microsoft in May 2026 — use a Teams **Workflows (Power Automate)** webhook. `interfaces/teams_notifier.py`: `notify(answer)` posts a MessageCard (title = top finding, text = answer + top recommendation + dashboard link as plain URL; buttons don't render via Workflows). Send only when a finding is `critical` or an alert threshold is breached (configurable). Wire behind `if TEAMS_WEBHOOK_URL`.

## Acceptance criteria
- [ ] Chat app runs; clicking each example chip returns a readable, grounded answer card within ~60s.
- [ ] "Is payment over-provisioned?" returns real numbers + a right-sizing verdict (the flagship demo answer).
- [ ] "How is the system doing?" on a quiet system returns a healthy verdict with numbers.
- [ ] Live resource table shows real per-service CPU/mem from `/resource-summary`.
- [ ] After running `adHighCpu`, the alert banner appears; clicking it produces an analysis recommending a scale-up.
- [ ] "Recent AI analyses" panel in Grafana shows results after a few questions.
- [ ] (Stretch) Teams receives a formatted message on a critical alert.
