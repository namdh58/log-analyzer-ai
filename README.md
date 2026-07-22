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

1. **Clone the demo** (pinned to a release tag, not `main`):
   ```bash
   git clone --branch v2.2.0 https://github.com/open-telemetry/opentelemetry-demo otel-demo
   ```

2. **Bring up the stack** (demo + Tempo/Loki overrides). Always run from the repo root, with the
   demo compose file listed first — the override file's relative paths resolve against it:
   ```bash
   docker compose -f otel-demo/docker-compose.yml -f overrides/docker-compose.override.yml up -d
   ```
   Verify: shop UI at http://localhost:8080, Grafana at http://localhost:3000 (Prometheus, Loki,
   Tempo datasources all query OK).

   Let the load generator run for **~15 min** before demoing questions like "is this
   over-provisioned?" — right-sizing answers need real utilization history.

3. **Python deps** — no pinned lockfile in this repo; install what's imported:
   ```bash
   python3 -m pip install --user pydantic fastapi uvicorn requests pyyaml langgraph pytest
   ```
   (If your host blocks system pip installs, add `--break-system-packages`, or use a venv if one is available.)

4. **Configure `.env`** (copy from `.env.example`):
   ```bash
   cp .env.example .env
   ```
   Minimum to run: set `LLM_PROVIDER` (`anthropic` default) and its API key
   (`ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY`, or point `OLLAMA_URL` at a local Ollama for a
   zero-API-cost run). `SEARCH_PROVIDER=none` works fine; `tavily`/`anthropic` add web search.

## Running it

**Chat dashboard** (primary interface):
```bash
python -m interfaces.dashboard.app
```
Open http://localhost:8500.

**Background scanner** (polls for anomalies every 60s, fires an alert into the chat/history when found):
```bash
python -m scripts.scheduled_scan
```

**Scripted demo** (3-act presenter-paced run — healthy questions, live CPU alert, live payment failure):
```bash
python -m scripts.run_demo               # all 3 acts, paced with [Enter]
python -m scripts.run_demo --act 2        # just one act
python -m scripts.run_demo --no-pause     # unattended dry-run
```

**Tests**:
```bash
python -m pytest                          # unit/deterministic tests (fast, run against fixtures)
python -m pytest -m e2e                   # smoke tests against the live stack (slow)
```

## Triggering chaos scenarios

All failures are existing `flagd` flags in `otel-demo/src/flagd/demo.flagd.json`, flipped by editing
that file in place (flagd hot-reloads it — no restart needed). `chaos/flags.py` does the edit;
`chaos/scenarios.py` wraps it into named, timed runs.

**Run one scenario end-to-end** (enables the flag, waits, disables it, logs to `chaos/injected_events.log`):
```bash
python -m chaos.scenarios <name> [--duration 120]
```

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
interfaces/dashboard FastAPI chat app + static UI
results/            analysis_history.jsonl + saved conversations
scripts/            run_demo.py (presenter demo), scheduled_scan.py (background scanner)
tests/              pytest — fixtures-based unit tests + `-m e2e` live smoke tests
docs/               PHASE1-5.md (specs) + EXPECTED-PHASE1-5.md (verification checklists)
```

## Custom Claude Code commands

- `/phase <n>` — work a project phase's acceptance criteria in order.
- `/verify <n>` — check a phase against its EXPECTED checklist (verify only, no edits).
- `/scenario <name>` — run one chaos scenario end-to-end, show detection → analyst answer.
- `/handoff` — update PROGRESS.md from git state at the end of a session.
