# PHASE 1 — Infrastructure & Failure Injection (Day 1)

Read CLAUDE.md first. Goal: OpenTelemetry Demo running via Docker Compose with traces in **Tempo**, logs in **Loki**, metrics in **Prometheus**, all visible in Grafana — plus scriptable failure injection via flagd flags.

## 1.1 Deploy OpenTelemetry Demo
- `git clone https://github.com/open-telemetry/opentelemetry-demo otel-demo` (pin to latest release tag, record tag in PROGRESS.md).
- Bring it up with the stock `docker compose up -d` FIRST and verify the shop works at http://localhost:8080 before changing anything. The demo ships with its own OTel Collector, Prometheus, Grafana, Jaeger, OpenSearch, Kafka, and a load generator (keep the load generator running — it provides baseline traffic for Phase 2 baselines).
- Note total RAM usage; if host is tight, disabling OpenSearch (step 1.2) frees the most.

## 1.2 Swap trace/log backends: Jaeger → Tempo, OpenSearch → Loki
Do this via `overrides/docker-compose.override.yml` + config files in `overrides/` — do NOT edit files inside `otel-demo/` except the collector config it mounts (if a mount override is cleaner, prefer that).
- Add **Tempo** service (single-binary, local storage). Collector traces pipeline: replace Jaeger exporter with `otlp` exporter → Tempo (gRPC 4317 or HTTP 4318). Expose Tempo HTTP API on 3200.
- Add **Loki** service (v3.x, single-binary) with **native OTLP ingestion enabled**. Collector logs pipeline: `otlphttp` exporter → `http://loki:3100/otlp`. Remove/disable the OpenSearch exporter and the `opensearch` + related dashboard services.
- Keep the demo's Prometheus untouched.
- Grafana: add provisioned datasources for Tempo and Loki (the demo already provisions Prometheus). Enable trace-to-logs correlation in the Tempo datasource (link via trace_id → Loki) if quick; otherwise skip.
- Verify demo services' logs actually flow through the collector (most demo services emit OTLP logs; for any that only write stdout, it is acceptable to lose them — do NOT add Promtail unless a demo-critical service is missing from Loki).

## 1.3 Verify telemetry correlation (critical for later phases)
- Place an order in the shop UI. Then confirm:
  - Tempo: can fetch the checkout trace by trace_id (find one via Grafana Explore).
  - Loki: LogQL query returns log lines for that same trace_id (OTLP-ingested logs carry trace_id as structured metadata/attribute — record the exact label/attribute name in PROGRESS.md "Verified facts").
  - Prometheus: latency histogram + request-count metrics exist per service (record exact metric names, e.g. from spanmetrics or the demo's own metrics, in PROGRESS.md).

## 1.4 Failure injection (`chaos/`)
No service patching. Failures come from flagd feature flags.
- First, read `otel-demo/src/flagd/demo.flagd.json` and list all available flags. Update the scenario table in CLAUDE.md if actual flag names differ.
- `chaos/flags.py`: functions `set_flag(name, variant)` and `reset_all()` — edit `demo.flagd.json` in place (flagd hot-reloads the mounted file; verify hot-reload works, else fall back to instructing use of the flagd UI at http://localhost:8080/feature).
- `chaos/scenarios.py`: CLI `python -m chaos.scenarios <name> [--duration 120]` for the 4 scenarios in CLAUDE.md. Each run: enable flag → wait duration → disable flag → append to `chaos/injected_events.log` one JSON line: `{"scenario","flag","start","end"}` (ISO timestamps). No trace_ids upfront — detection is time-window based; the pipeline discovers affected trace_ids itself.
- `reset_all()` must also run on Ctrl+C (so a crashed demo never leaves flags on).

## 1.5 Capture golden fixtures (do LAST, before closing the phase)
After telemetry is verified working, capture real samples into `tests/fixtures/` for deterministic testing in later phases:
- `trace_sample.json` — one full trace fetched from Tempo (a checkout trace).
- `logs_sample.json` — the log lines for that same trace_id from Loki.
- `metrics_sample.json` — a Prometheus query result block (latency + error rate for one service over a window).
- `flagd_flags.json` — the list of available flag names (so later phases don't guess).
Record in PROGRESS.md which trace_id these came from.

## Acceptance criteria
- [ ] `docker compose up` (demo + overrides) starts everything; shop UI works, an order completes.
- [ ] Grafana shows 3 working datasources: Prometheus, Loki, Tempo (one successful query each).
- [ ] For one real trace_id: trace visible in Tempo AND matching log lines retrievable from Loki by that trace_id.
- [ ] Each of the 4 scenarios runs via CLI, produces visible effect (errors/latency in Grafana), writes correct entry to `injected_events.log`, and cleanly resets its flag.
- [ ] PROGRESS.md "Verified facts" section filled in (flag names, Loki labels, Tempo endpoint, Prometheus metric names).
- [ ] `tests/fixtures/` contains the 4 golden fixture files captured from real telemetry.
