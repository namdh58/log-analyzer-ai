# PHASE 2 — Retrieval Layer, Signal Detector, Masking (Day 1 pm – Day 2 am)

Read CLAUDE.md + PROGRESS.md "Verified facts" first (exact metric/label names come from there, not from assumptions). Depends on Phase 1.

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
- `search_traces(start, end, service=None, error_only=False, limit=20) -> list[trace_id]` (TraceQL)

`metric_client.py` — class `MetricClient` (Prometheus HTTP API):
- `get_latency_p95(service, start, end) -> list[float]`
- `get_error_rate(service, start, end) -> float`
- `get_request_rate(service, start, end) -> float`
- `get_kafka_consumer_lag(start, end) -> float` (demo exposes Kafka metrics via collector)
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
| span_gap | for error/incomplete traces in window (via TraceClient): expected child span missing per `service_map.yaml` (e.g. checkout → payment) | any missing required child |
| queue_lag | Kafka consumer lag / publish-vs-consume delta | lag > threshold or growing over window |
| throughput_drop | request rate vs baseline | < 50% baseline |

- `detection/service_map.yaml`: static call map of the Astronomy Shop (frontend → cart/product-catalog/checkout/recommendation/ad; checkout → cart/payment/shipping/email/currency; checkout → kafka → accounting/fraud-detection). Verify service names against real telemetry from Phase 1.
- When a signal fires, populate `affected_trace_ids` with up to 5 example trace_ids (via `TraceClient.search_traces(error_only=True)` or Loki error lines in window).
- Multiple signals may fire for one window — return all.

## Acceptance criteria
- [ ] `LogClient.get_logs_by_trace_id` returns correct, masked logs for a real trace from Phase 1.
- [ ] `TraceClient.get_trace` returns a correct span tree for that trace.
- [ ] `MetricClient` returns real latency/error-rate values.
- [ ] Masking unit-tested on a synthetic line containing fake email + token.
- [ ] Run each of the 4 chaos scenarios, then `detect()` over that window:
  - payment_failure → error_rate_spike fires
  - payment_outage → span_gap (and/or error_rate_spike) fires
  - queue_backlog → queue_lag fires
  - overload → latency_spike and/or throughput_drop fires
- [ ] Quiet window (no chaos) → no signals (or document false positives + tune thresholds).
