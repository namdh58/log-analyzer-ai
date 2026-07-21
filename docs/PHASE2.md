# PHASE 2 — Retrieval Layer, Signal Detector, Masking (Day 1 pm – Day 2 am)

Read CLAUDE.md + PROGRESS.md "Verified facts" first (exact metric/label names come from there, not from assumptions). Depends on Phase 1.

> ⚠️ **Two Phase-1 findings override parts of this spec — read PROGRESS.md, then apply these:**
> 1. **Payment spans do NOT flip to status=ERROR.** A failed payment shows up in Prometheus error-rate metrics, not as an errored span in Tempo. Error traces cannot be found by span-error filtering — find them via a metric-identified time window + service filter instead (see 2.1 and 2.3).
> 2. **queue_backlog manifests as a publish flood, not consumer lag.** The queue signal must detect a publish-rate spike / publish-vs-consume delta, not a growing consumer-lag metric (see 2.3).

## 2.1 Retrieval layer (`retrieval/`)
Shared Pydantic models in `retrieval/models.py`:
- `LogEntry`: timestamp, service, level, message, trace_id, span_id, raw
- `SpanNode`: trace_id, span_id, parent_span_id, service, operation, start, duration_ms, status, children (recursive)

`log_client.py` — class `LogClient` (Loki HTTP API):
- `get_logs_by_trace_id(trace_id) -> list[LogEntry]` (sorted by timestamp)
- `get_logs_by_time_range(start, end, service=None, levels=None) -> list[LogEntry]`
- Use the actual Loki label/structured-metadata names verified in Phase 1.

`trace_client.py` — class `TraceClient` (Tempo HTTP API):
- `get_trace(trace_id) -> SpanNode` (build the span tree)
- `search_traces(start, end, service=None, limit=20) -> list[trace_id]` (TraceQL, by time window + service)
- NOTE (Phase-1 finding): do NOT rely on an `error_only`/status-based filter to find failing traces — payment failures leave spans as status=OK. The primary way to locate a failing scenario's traces is: use `MetricClient` to identify WHEN and WHICH service is anomalous, then `search_traces(window, service=<that service>)` to pull the traces from that window. (Keep an optional status filter available for scenarios that DO error at span level, e.g. payment_outage, but never depend on it alone.)

`metric_client.py` — class `MetricClient` (Prometheus HTTP API):
- `get_latency_p95(service, start, end) -> list[float]`
- `get_error_rate(service, start, end) -> float`
- `get_request_rate(service, start, end) -> float`
- `get_kafka_publish_rate(start, end) -> float` and `get_kafka_consume_rate(start, end) -> float` — queue_backlog shows as a publish FLOOD, so compare publish vs consume rate (a large positive publish-minus-consume delta is the signal). Read the exact Kafka metric names from PROGRESS.md; if a direct consumer-lag metric exists and works, it can supplement, but publish-rate spike is the reliable indicator here.
- `get_baseline(service, metric) -> float`: mean over the 30 min preceding the queried window (load generator provides steady baseline traffic). If <30 min of data, use whatever exists and flag it.

## 2.2 Masking (`retrieval/masking.py`)
Regex-only. Patterns: email, phone, 16-digit card numbers, IPv4, JWT/long random tokens (alphanumeric > 20 chars), obvious `key=`/`token=`/`password=` values. Replace with `<EMAIL_MASKED>` etc.
`mask_log_entry(entry) -> LogEntry` applied to `message` and `raw`. `LogClient` applies masking to everything it returns — agents never see raw PII.

## 2.3 Generic signal detector (`detection/signal_detector.py`)
Pure Python, no LLM. Class `SignalDetector.detect(start, end) -> list[Signal]`.
`Signal` model: signal_type, confidence, affected_services, affected_trace_ids (may be filled lazily), metric_values, window (start,end).

5 signals, one independent `_check_*` method each, thresholds in `detection/config.yaml`:
| signal_type | Logic | Default threshold |
|---|---|---|
| latency_spike | p95 vs baseline per service | > 2x baseline |
| error_rate_spike | error rate vs baseline | > 3x baseline or > 10% |
| span_gap | for traces in the anomalous window (found via metric-identified time+service, NOT span-error filtering): expected child span missing per `service_map.yaml` (e.g. checkout present but payment child absent) | any missing required child |
| queue_anomaly | publish-vs-consume rate delta on Kafka (queue_backlog is a publish flood, not lag) | publish rate >> consume rate, or publish-rate spike vs baseline |
| throughput_drop | request rate vs baseline | < 50% baseline |

- `detection/service_map.yaml`: keep it SMALL — only the services the 4 scenarios touch, so span_gap doesn't throw false positives on unrelated services. Core map (verify exact service names against Phase-1 telemetry / PROGRESS.md before writing — names may be `payment` vs `paymentservice` etc.):
  ```yaml
  frontend: [cart, checkout, product-catalog, recommendation, ad]
  checkout: [cart, payment, shipping, currency, kafka]
  ```
  (Add the overload-scenario target — ad or recommendation — and the kafka consumers accounting/fraud-detection only if you actually assert on them.)
- When a signal fires, populate `affected_trace_ids` with up to 5 example trace_ids via `TraceClient.search_traces(window, service=<anomalous service>)` — the metric-identified-window approach, NOT span-error filtering (payment spans stay OK). Loki error lines in the window are a secondary source.
- Multiple signals may fire for one window — return all.

## Acceptance criteria
- [ ] `LogClient.get_logs_by_trace_id` returns correct, masked logs for a real trace from Phase 1.
- [ ] `TraceClient.get_trace` returns a correct span tree for that trace.
- [ ] `MetricClient` returns real latency/error-rate values.
- [ ] Masking unit-tested on a synthetic line containing fake email + token.
- [ ] Run each of the 4 chaos scenarios, then `detect()` over that window:
  - payment_failure → error_rate_spike fires (driven by Prometheus metrics, since spans stay OK)
  - payment_outage → span_gap (and/or error_rate_spike) fires
  - queue_backlog → queue_anomaly fires (publish-vs-consume delta)
  - overload → latency_spike and/or throughput_drop fires
- [ ] Quiet window (no chaos) → no signals (or document false positives + tune thresholds).
