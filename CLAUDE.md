# CLAUDE.md — Distributed Observability AI Copilot

Internal demo (3-day build). AI system that analyzes logs/traces/metrics from a real microservice cluster (OpenTelemetry Demo "Astronomy Shop") to detect and explain distributed failures. Answers 3 questions:
1. "Anything abnormal in this time window?"
2. "Anything abnormal in this trace_id?"
3. "What is this failure and how to fix it?"

Must actually run end-to-end (no full mocks). Not production. All user-facing text in **English**.

## Hard constraints
- Solo dev + Claude Code. 3 days. No CI/CD, only smoke tests.
- Docker Compose only (no Kubernetes).
- Failure injection = OpenTelemetry Demo built-in **flagd feature flags** (NO custom chaos code patching demo services).
- No custom MCP server. Web search = Anthropic server-side web search tool (anthropic provider only).
- Teams notification is OPTIONAL stretch (Phase 4). Dashboard chat is the primary interface.

## Tech stack (fixed)
| Component | Choice |
|---|---|
| Language | Python 3.11+ (uv or pip, single venv at repo root) |
| Source system | open-telemetry/opentelemetry-demo (Docker Compose) |
| Traces | OTel Collector → **Tempo** (replaces demo's Jaeger) |
| Metrics | Prometheus (ships with demo) |
| Logs | OTel Collector → **Loki** via native OTLP ingestion (replaces demo's OpenSearch) |
| Dashboards | Grafana (ships with demo; add Tempo+Loki datasources) |
| Agent orchestration | LangGraph |
| LLM | Pluggable via `LLM_PROVIDER`: `anthropic` (default) · `openrouter` (session addition) · `ollama` (local) |
| Anthropic models | fast (light tasks): `claude-haiku-4-5` · smart (analysis): `claude-sonnet-4-6` |
| OpenRouter fallback | `deepseek/deepseek-chat` via https://openrouter.ai — used when no `ANTHROPIC_API_KEY` is available yet. Same tier for fast/smart. No web search in this mode. |
| Ollama fallback | `qwen2.5:7b-instruct` (fits RTX 3080 8GB, JSON mode). No web search in this mode. |
| PII masking | Regex-based (skip Presidio — too heavy for demo) |

## Repo layout
```
observability-ai-copilot/
├── CLAUDE.md  PROGRESS.md  .env  .env.example
├── otel-demo/                  # git clone of opentelemetry-demo (do NOT vendor into git)
├── overrides/                  # docker-compose.override.yml + tempo/loki/grafana configs
├── chaos/                      # flag toggle scripts + injected_events.log
│   ├── flags.py                # toggle any flagd flag on/off via demo.flagd.json edit
│   └── scenarios.py            # 4 named scenarios (see Scenarios)
├── retrieval/                  # log_client.py  metric_client.py  trace_client.py  masking.py
├── detection/                  # signal_detector.py  service_map.yaml  config.yaml
├── agents/                     # schemas.py  llm.py  context_builder.py  analyst.py  orchestrator.py
├── interfaces/dashboard/       # app.py (FastAPI)  static/index.html
├── results/                    # analysis_history.jsonl
├── scripts/                    # run_demo.py  scheduled_scan.py
└── tests/                      # test_e2e_scenario.py
```

## Env vars (.env — always keep .env.example in sync)
```
LLM_PROVIDER=anthropic          # anthropic | openrouter | ollama
ANTHROPIC_API_KEY=
OPENROUTER_API_KEY=             # openrouter provider (deepseek/deepseek-chat), no web search
OPENROUTER_MODEL=deepseek/deepseek-chat
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b-instruct
LOKI_URL=http://localhost:3100
PROMETHEUS_URL=http://localhost:9090
TEMPO_URL=http://localhost:3200
GRAFANA_URL=http://localhost:3000
FLAGD_CONFIG_PATH=./otel-demo/src/flagd/demo.flagd.json
DASHBOARD_URL=http://localhost:8500
TEAMS_WEBHOOK_URL=              # optional, Workflows webhook (Phase 4 stretch)
```

## Failure scenarios (all via flagd flags — read exact flag names from demo.flagd.json first, do not hardcode from memory)
| Scenario name | flagd flag (approx name) | Expected signals | Expected anomaly_type |
|---|---|---|---|
| payment_failure | paymentFailure → 100% | error_rate_spike | service_failure |
| payment_outage | paymentUnreachable → on | span_gap + error_rate_spike | broken_trace / timeout |
| queue_backlog | kafkaQueueProblems → on | queue_anomaly (publish flood) | message_loss |
| overload | adHighCpu (or loadgeneratorFloodHomepage) → on | latency_spike (+ throughput_drop) | resource_exhaustion |

## Product framing (Phase 3+ — changed from original plan)
This is an **infrastructure analyst copilot**, not just an anomaly detector. Core = a single analyst agent + chat interface that reads logs/traces/metrics/**resource utilization (CPU/mem vs limits)** and answers ANY question: failures, performance, right-sizing ("is this service over-provisioned?"), capacity/scaling, or "system is healthy". The 4 chaos failures are ONE capability, not the whole product. Chat is the demo centerpiece. Each container = a resource-capped service (honest framing, not fake EC2). Detector/signals feed the analyst as trusted context but are NOT a hard gate — the analyst answers even when nothing is wrong.

## Conventions
- Pydantic v2 models everywhere agents exchange data. Core output schema = `AnalystAnswer` (answer text + findings + recommendations). See docs/PHASE3.md.
- All data leaving `retrieval/` is already PII-masked.
- Signal detection is pure Python (no LLM). LLM calls only inside `agents/`. The analyst must ground every claim in retrieved telemetry — NEVER invent numbers. If it invents numbers, the fix is in the context builder (feed real data), not the prompt.
- Every analysis run appends one JSON line to `results/analysis_history.jsonl` AND pushes a compact log line to Loki (service="ai-copilot").
- Log LLM call count + token usage per run (printed at end).
- Analyst retry loop (widen context on insufficient data) = max 2.

## Verification & self-fix loop
- **Deterministic code** (retrieval, masking, detection, schemas, orchestrator wiring): write a test with CONCRETE expected values before/alongside the implementation, run it, and self-fix until green. Do not mark a criterion done until its test passes — show the passing output.
- **Golden fixtures**: at the end of Phase 1, save real captured samples to `tests/fixtures/` (one real Tempo trace JSON, a batch of real Loki log lines, a real Prometheus metric block). Deterministic tests run against these fixed fixtures, not live infra — fast, repeatable, gives a real expected output to diff against.
- **LLM-judgment code** (analyst answers): NO hard-assert self-fixing. The key check is GROUNDING — do the numbers in the answer actually appear in the fetched telemetry? Print the answer + evidence for the human to review. If it hallucinated numbers, fix the context builder, not the prompt.
- **Debug output discipline**: never dump full container logs or full JSON API responses into the conversation — it burns context fast. Use `docker compose logs <svc> --tail 50`, `curl ... | head -30`, `jq` to extract only needed fields, grep before showing.
- Phase specs live in `docs/PHASEn.md`; each has a matching `docs/EXPECTED-PHASEn.md` the human uses to eyeball-verify. Match reality against it before moving on.

## Session workflow (Claude Code)
1. Read PROGRESS.md before doing anything.
2. Work one phase per session (PHASE1..PHASE5 files).
3. `git commit` after each acceptance criterion passes.
4. Before ending a session: update PROGRESS.md (done / decisions that deviate from plan / next step).

## Custom slash commands (in `.claude/commands/`)
- `/phase <n>` — start a session on phase n (reads memory, works criteria in order, commits per criterion).
- `/verify <n>` — check a phase against its EXPECTED-PHASEn.md, report pass/fail per check (verify only, no edits).
- `/scenario <name>` — run one chaos scenario end-to-end and show detection→analyst answer.
- `/handoff` — end-of-session: update PROGRESS.md from real git state so the next session continues cleanly.
Typical day: `/phase 2` … work … `/verify 2` … fix … `/handoff`.
