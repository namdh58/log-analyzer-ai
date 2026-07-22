# Distributed Observability AI Copilot

An AI copilot that reads real logs, traces, metrics, and resource utilization from a running
microservice cluster ([OpenTelemetry Demo "Astronomy Shop"](https://github.com/open-telemetry/opentelemetry-demo))
and answers infrastructure questions in a chat UI:

- "Anything abnormal in this time window?"
- "Anything abnormal in this trace_id?"
- "What is this failure and how to fix it?"
- ...plus health checks, right-sizing, and capacity questions — it's an analyst, not just a failure detector.

Internal 3-day demo build. Not production. See `CLAUDE.md` for the full spec and `PROGRESS.md` for build history/decisions.

## Architecture

```
otel-demo (docker compose)          overrides/ (docker compose)
  shop services + load generator      Tempo (traces), Loki (logs, native OTLP)
  Kafka, flagd (feature flags)        Prometheus stays stock, Grafana +Tempo/Loki datasources
              \                          /
               \                        /
                v                      v
        retrieval/ (log/metric/trace clients + PII masking)
                      |
              detection/ (pure-Python signal detector: error rate, latency,
                          queue backlog, throughput, cpu/mem vs limits)
                      |
              agents/ (LangGraph orchestrator: extract → RCA → fix,
                       LLM_PROVIDER: anthropic | deepseek | ollama)
                      |
          interfaces/dashboard (FastAPI chat UI, localhost:8500)
```

Failures are injected via **flagd feature flags** already built into the OTel demo (no chaos code
patching the demo services). See `chaos/` and "Triggering chaos scenarios" below.

## Setup

1. **Clone the demo** (pinned to a release tag, not `main` — this repo was built and verified against `2.2.0`):
   ```bash
   git clone --branch 2.2.0 https://github.com/open-telemetry/opentelemetry-demo otel-demo
   ```

2. **Bring up the stack** (demo + Tempo/Loki overrides). Always run from the repo root, with the
   demo compose file listed first — the override file's relative paths resolve against it:
   ```bash
   docker compose -f otel-demo/docker-compose.yml -f overrides/docker-compose.override.yml up -d
   ```
   Verify (all confirmed working live): shop UI at http://localhost:8080 → 200, Grafana at
   http://localhost:3000/api/health → 200, Prometheus http://localhost:9090/-/healthy,
   Loki http://localhost:3100/ready, Tempo http://localhost:3200/ready. Loki/Tempo legitimately
   cycle through a harmless `503 "waiting for 15s after being ready"` right after a fresh restart —
   don't worry unless it's still 503 a minute later.

   Let the load generator run for **~15 min** before demoing questions like "is this
   over-provisioned?" — right-sizing answers need real utilization history.

3. **Python deps** — there's no `requirements.txt`/`pyproject.toml` in this repo (a deliberate gap
   noted in `PROGRESS.md`) and the `.venv` if present at repo root is a leftover from a Playwright
   experiment (only has `playwright`/`greenlet` in it) — **don't use it for the app**. Install
   straight to user site-packages instead:
   ```bash
   python3 -m pip install --user pydantic fastapi uvicorn requests pyyaml langgraph pytest anthropic openai
   ```
   (Add `--break-system-packages` if pip refuses on an externally-managed system Python.)

4. **Configure `.env`** (copy from `.env.example`):
   ```bash
   cp .env.example .env
   ```
   Set `LLM_PROVIDER` (`anthropic` default) and its key (`ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY`),
   or point `OLLAMA_URL` at a local Ollama for a zero-API-cost run (no Ollama server was reachable
   in this environment when checked — install/start one first if you want that path).

   **Important, verified by running it: `.env` is not auto-loaded.** Only `chaos/flags.py` reads it
   itself. Every other entry point (`interfaces.dashboard.app`, `scripts.run_demo`,
   `scripts.scheduled_scan`, the test suite) just reads `os.environ` directly — if you only have a
   `.env` file and never exported it, `LLM_PROVIDER` silently falls back to `anthropic` with no key
   and every analysis call crashes with a 500. Export it into the shell first:
   ```bash
   set -a && source .env && set +a
   ```
   Do this once per shell/session before any of the commands below.

## Running it

**Chat dashboard** (primary interface):
```bash
set -a && source .env && set +a
python3 -m interfaces.dashboard.app
```
Open http://localhost:8500 (confirmed serving `index.html`, 200). Posting a question to `/ask` runs
the full LangGraph pipeline; **as of this check, the configured `DEEPSEEK_API_KEY` is an OpenRouter
key that's out of credit (`402` from every `/ask` call)** — this matches the known issue already
logged in `PROGRESS.md`. Top up OpenRouter, switch to a real `ANTHROPIC_API_KEY`, or run Ollama
locally before demoing.

**Chaos control panel** (button-driven UI to trigger/stop scenarios + reset for a clean demo take —
see "Triggering chaos scenarios" below for full details):
```bash
python3 -m interfaces.chaos_panel.app
```
Open http://localhost:8600.

**Background scanner** (polls for anomalies every 60s, fires an alert into the chat/history when found):
```bash
set -a && source .env && set +a
python3 -m scripts.scheduled_scan
```

**Scripted demo** (3-act presenter-paced run — healthy questions, live CPU alert, live payment failure):
```bash
set -a && source .env && set +a
python3 -m scripts.run_demo               # all 3 acts, paced with [Enter]
python3 -m scripts.run_demo --act 2        # just one act
python3 -m scripts.run_demo --no-pause     # unattended dry-run
```

**Tests** — `pytest.ini` only *registers* the `e2e` marker, it doesn't deselect it, and one file
(`tests/test_detection_scenarios.py`) runs real 180s+ chaos scenarios against the live stack without
even being marked `e2e`. Confirmed live: a bare `python -m pytest` hangs for 15+ minutes firing real
chaos scenarios — it is **not** a fast/offline command here despite the name. Use:
```bash
# fast, deterministic-ish (still hits live Loki/Tempo/Prometheus for real numbers, ~2s)
python3 -m pytest -q --ignore=tests/test_detection_scenarios.py -m "not e2e"

# slow, live chaos scenarios (~15+ min total)
python3 -m pytest tests/test_detection_scenarios.py -v -s

# slow, live chaos + real LLM calls (~8 min, needs working LLM credentials)
python3 -m pytest tests/test_e2e_scenario.py -v -s -m e2e
```
Note: a couple of the "fast" tests (`test_retrieval.py`, `test_context_builder.py`) query a
hardcoded historical `trace_id` against the live Tempo/Loki — they can fail after
`docker compose down -v` or once local retention ages that trace out, independent of any code change.

## Triggering chaos scenarios

All failures are existing `flagd` flags in `otel-demo/src/flagd/demo.flagd.json`, flipped by editing
that file in place (flagd hot-reloads it — no restart needed). `chaos/flags.py` does the edit;
`chaos/scenarios.py` wraps it into named, timed runs.

### Chaos control panel (API + UI, no CLI needed)

`interfaces/chaos_panel` is a separate small FastAPI service — a button-driven UI to run/stop each
scenario and to reset the environment between demo takes, so you don't need a terminal during the demo.
```bash
python3 -m interfaces.chaos_panel.app
```
Open **http://localhost:8600**. Confirmed live: starting a scenario flips the flag immediately and runs
it in the background (HTTP call returns right away, no blocking); only one scenario can run at a time
(a second `start` while one is active returns `409`); **Stop** cancels the wait early, resets the flag
immediately, and still logs the correct (shortened) end time.

The panel also has a **"Run order + fetch logs"** button — this drives the shop's actual main
checkout logic (add-to-cart → checkout, exactly what the demo's own load generator does) rather than
any chaos flag, and returns the resulting `trace_id` plus its logs, so you can confirm log
retrieval/correlation works *before* testing a failure case. Confirmed live end-to-end: a manually
crafted `traceparent: 00-<trace_id>-<span_id>-01` header sent on the cart/checkout calls propagates
through `frontend-proxy` → `cart` → `checkout` (all OTel-instrumented services honor an incoming W3C
trace context by default), so the trace_id we generate is the real one — Tempo returned the full trace
and Loki returned 20 real log lines keyed to it, no polling needed once ingestion caught up (confirmed
both the `wait=0` empty-immediately case and the `wait=10` case that then found the logs ~1s later).

Endpoints, if you want to script it:

| Endpoint | Effect |
|---|---|
| `POST /normal-flow/run` | places one **real** order through the shop's own add-to-cart + checkout logic (no chaos) with a hand-crafted W3C `traceparent` header, and returns the resulting `trace_id` |
| `GET /logs/{trace_id}?wait=10` | fetches that trace's logs from Loki, polling up to `wait` seconds since ingestion lags a few seconds behind the request |
| `GET /status` | current running scenario (if any) + live flagd state of all 4 flags |
| `POST /scenarios/{name}/start?duration=180` | start a case (`payment_failure`, `payment_outage`, `queue_backlog`, `overload`) |
| `POST /scenarios/{name}/stop` | cancel early, flag reset immediately |
| `POST /reset` | **clean environment for a fresh case**: force all flags off, then archive (not delete) any non-empty `results/analysis_history.jsonl`, `results/conversations/`, `chaos/injected_events.log` into `results/archive/<timestamp>/` and leave those paths empty — so the dashboard's history/conversation list and the injected-events log start clean for the next case, without losing prior runs. Confirmed live: after reset, `results/analysis_history.jsonl` no longer exists (dashboard's `/history` already tolerates a missing file → returns `[]`) and the old data sat untouched under `results/archive/20260722T164001Z/`. |

Note: if `scripts.scheduled_scan` is running as its own process, its 5-minute dedupe memory isn't
touched by `/reset` — restart that process too if you want it to re-fire on a repeated signal right away.

**Run one scenario end-to-end** (CLI alternative, blocks until done) (enables the flag, waits, disables it, logs to `chaos/injected_events.log`):
```bash
python3 -m chaos.scenarios <name> [--duration 120]
```
Confirmed live (`python3 -m chaos.scenarios overload --duration 5`): flag flips to `on`, waits, then
resets to `off` in `otel-demo/src/flagd/demo.flagd.json` — no restart needed, flagd hot-reloads the
mounted file. `payment_failure`/`payment_outage`/`queue_backlog` need real checkout traffic to
manifest, so PROGRESS.md's own scenario tests use **180s**, not the 120s default — expect to bump
`--duration` for those three on a low-traffic stack.

| Scenario name | flagd flag | Expected signal | Expected anomaly_type |
|---|---|---|---|
| `payment_failure` | `paymentFailure` → 100% | error_rate_spike | service_failure |
| `payment_outage` | `paymentUnreachable` → on | span_gap + error_rate_spike | broken_trace / timeout |
| `queue_backlog` | `kafkaQueueProblems` → on | queue_anomaly | message_loss |
| `overload` | `adHighCpu` → on | latency_spike (+ throughput_drop) | resource_exhaustion |

Ctrl+C during a run resets all flags to off automatically (`install_signal_handlers`), so a killed
scenario never leaves the demo broken.

**Manual flag control** (no timer, e.g. to leave a failure running while you poke around):
```python
from chaos.flags import set_flag, reset_all
set_flag("paymentFailure", "100%")   # or "adHighCpu", "on" etc.
reset_all()                          # turn everything back off
```

Or flip flags directly in the flagd UI at http://localhost:8080/feature.

**End-to-end via Claude Code**: `/scenario <name>` runs the scenario, waits for telemetry to land,
then runs detection + the full agent pipeline and reports signals → RCA → fix, step by step — the
fastest way to sanity-check the pipeline after a change.

## Repo layout

```
otel-demo/          git clone of opentelemetry-demo (not vendored into this repo's git)
overrides/          docker-compose.override.yml + Tempo/Loki/Grafana configs
chaos/              flags.py (edit demo.flagd.json), scenarios.py (named timed runs)
retrieval/          log/metric/trace clients + PII masking — everything leaving here is masked
detection/          pure-Python signal detector (no LLM)
agents/             schemas, LLM client (anthropic/deepseek/ollama), web search, context builder,
                    analyst, LangGraph orchestrator
interfaces/dashboard    FastAPI chat app + static UI (localhost:8500)
interfaces/chaos_panel  FastAPI chaos control panel: start/stop scenarios, reset env (localhost:8600)
results/            analysis_history.jsonl + saved conversations (+ archive/ from chaos_panel resets)
scripts/            run_demo.py (presenter demo), scheduled_scan.py (background scanner)
tests/              pytest — mostly fast (some still hit live infra), plus 2 live-chaos files
                    that are slow/expensive and must be run explicitly (see "Tests" above)
docs/               PHASE1-5.md (specs) + EXPECTED-PHASE1-5.md (verification checklists)
```

## Custom Claude Code commands

- `/phase <n>` — work a project phase's acceptance criteria in order.
- `/verify <n>` — check a phase against its EXPECTED checklist (verify only, no edits).
- `/scenario <name>` — run one chaos scenario end-to-end, show detection → analyst answer.
- `/handoff` — update PROGRESS.md from git state at the end of a session.
