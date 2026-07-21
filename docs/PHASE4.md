# PHASE 4 — Dashboard & Chat Interface (Day 3 am)

Read CLAUDE.md + PROGRESS.md first. Depends on Phase 3. Primary interface = web dashboard with chat. Teams = optional stretch, do LAST.

## 4.1 Grafana panels
Add one provisioned dashboard "AI Copilot Overview" (JSON in `overrides/grafana/dashboards/`):
- Error timeline: Loki query, ERROR count by service over time (heatmap or stacked bars).
- Latency + error rate: Prometheus, p95 latency and error rate per service (line charts).
- Recent RCA results: Loki panel filtered `service="ai-copilot"` — the persist node from Phase 3 already writes results there. Format the pushed log line so hypothesis + anomaly_type are readable in the panel (compact JSON with key fields first).

## 4.2 Chat web app (`interfaces/dashboard/`)
- `app.py`: FastAPI on port 8500.
  - `POST /ask {question}` → Orchestrator with `trigger_type="user_question"` → returns full result JSON (extraction, rca, fix). This call can take 30-90s: implement as simple long request first; add polling/SSE only if time allows.
  - `GET /history` → last 20 lines of `results/rca_history.jsonl`.
  - `GET /` → serves static/index.html.
- `static/index.html`: vanilla JS, no build tools. Layout: chat box + answer cards (hypothesis, confidence, evidence list, fix, references) on one side; embedded Grafana panels (iframe, kiosk mode URLs) on the other; history list below. Show a visible "analyzing…" state while /ask runs. Clean minimal styling, dark theme to match Grafana.
- Example question that must work: "anything abnormal in trace <id>?" and "what happened in the last 10 minutes?" (the latter maps to a time_range trigger).

## 4.3 Teams notifier — OPTIONAL stretch (skip if behind schedule)
- IMPORTANT: classic Office 365 Connector incoming webhooks were permanently disabled by Microsoft in May 2026. Use a **Teams Workflows (Power Automate) webhook** — created via the Workflows app in the Teams channel ("When a Teams webhook request is received" template). MessageCard payloads still work through it, but interactive buttons do NOT render — put the dashboard link as plain URL text, not a potentialAction button.
- `interfaces/teams_notifier.py`: `notify(rca, fix)` posting a MessageCard (title with anomaly_type, facts: services/confidence, text: hypothesis + recommendation + dashboard URL).
- Send only when severity=="critical" OR confidence > 0.7 (configurable). Wire into the persist node behind `if TEAMS_WEBHOOK_URL`.

## Acceptance criteria
- [ ] Grafana dashboard shows error timeline + latency/error-rate with real data.
- [ ] After a pipeline run, the RCA result is visible in the Grafana "Recent RCA results" panel.
- [ ] Chat app: asking about a real trace_id returns a readable answer card; time-window question works too.
- [ ] (Stretch) Teams channel receives a correctly formatted message after a chaos scenario run.
