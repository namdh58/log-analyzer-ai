# EXPECTED OUTPUT — Phase 2 (Retrieval + Detection + Masking)

Phase 2 is mostly deterministic Python, so most of this is "run the test, see green". Fixtures from Phase 1 give you fixed expected values.

---

## Check 1 — LogClient returns real, sorted, masked logs
**Run:** a small script / pytest that calls `LogClient.get_logs_by_trace_id("<fixture trace_id>")`.
**Expect:** a `list[LogEntry]`, length > 0, sorted by timestamp ascending. Each entry has all fields populated (service, level, message, trace_id, span_id). Any email/token/card in messages is replaced with `<..._MASKED>`.
**If it's wrong:**
- Empty list for a trace_id you KNOW has logs → the LogQL query uses the wrong label name. Cross-check with the label recorded in PROGRESS.md.
- Fields blank → the OTLP log attribute names in Loki don't map to your model fields. Print one raw Loki response with `jq` and map fields by hand.

## Check 2 — TraceClient builds a correct span tree
**Run:** `TraceClient.get_trace("<fixture trace_id>")`.
**Expect:** a `SpanNode` with children. For a checkout trace you should see the shape: frontend → checkout → (payment, shipping, cart, currency, email). Parent/child links correct, durations present.
**If it's wrong:** flat list with no nesting → parent_span_id linking is broken. All-empty → Tempo query format wrong (verify the endpoint that worked in Phase 1).

## Check 3 — MetricClient returns real numbers
**Run:** `get_latency_p95("checkout", ...)`, `get_error_rate("payment", ...)`, `get_kafka_consumer_lag(...)`.
**Expect:** plausible non-zero floats (latency in ms, error rate 0.0–1.0). During a quiet window error_rate near 0.
**If it's wrong:** `None`/empty → PromQL uses a metric name that doesn't exist. List real metric names: `curl http://localhost:9090/api/v1/label/__name__/values | jq` and grep for latency/duration/errors.

## Check 4 — Masking unit test
**Run:** `mask_log_entry` on a synthetic line: `"user john@example.com paid with 4111111111111111 token=abcd1234efgh5678ijkl9012"`.
**Expect exactly:** email → `<EMAIL_MASKED>`, card → `<CARD_MASKED>`, token → `<TOKEN_MASKED>`. Non-sensitive words untouched.
**If it's wrong:** over-masking (eating normal words) or under-masking → tighten/loosen the specific regex. This one must be 100% green.

## Check 5 — Detector fires correctly per scenario (THE core check)
For each scenario: run chaos → wait for ingest → `SignalDetector.detect(start, end)` over that window. Print the returned signals.

| You run | Expected signal(s) in output |
|---|---|
| `payment_failure` | `error_rate_spike` (service: payment) |
| `payment_outage` | `span_gap` (checkout→payment missing) and/or `error_rate_spike` |
| `queue_backlog` | `queue_lag` |
| `overload` | `latency_spike` and/or `throughput_drop` |

Each `Signal` should carry: signal_type, confidence, affected_services (the right one), and ≥1 affected_trace_id.
**If it's wrong:**
- Right scenario, no signal → threshold too high, or baseline window overlaps the chaos window (baseline must be from BEFORE chaos). Print the actual metric value vs baseline vs threshold to see which.
- `queue_lag` never fires → the Kafka lag metric isn't exposed as expected; fall back to detecting the fraud-detection "sleeping" log lines or producer-vs-consumer span counts (noted as fallback in PHASE2).
- `span_gap` never fires → service_map.yaml service names don't match real telemetry names (e.g. `payment` vs `paymentservice`). Fix names to match reality.

## Check 6 — Quiet window is quiet
**Run:** `detect()` over a window with NO chaos.
**Expect:** empty list, or only weak/explainable signals.
**If it's wrong:** constant false positives → thresholds too tight for your machine's baseline noise. Raise them in `config.yaml` and note the new values.

---
### Phase 2 is DONE when
Checks 1-4 have passing tests (green, against fixtures), Check 5 fires the right signal for all 4 scenarios, and Check 6 is clean. This is the layer the agents trust as "ground truth" — if a signal is wrong here, the AI will confidently explain the wrong thing later. Get this solid.
