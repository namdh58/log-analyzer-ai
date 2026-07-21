# EXPECTED OUTPUT — Phase 1 (Infrastructure)

Use this to eyeball-verify Phase 1 yourself. Left = what you do. Right = what a PASS looks like. If reality differs, see "If it's wrong".

---

## Check 1 — Whole stack is up
**Run:** `docker compose ps` (from otel-demo with overrides)
**Expect:** ~25-30 containers, all `running`/`healthy`. Must include: `frontend`, `frontend-proxy`, `checkout`, `payment`, `cart`, `kafka`, `otel-collector`, `prometheus`, `grafana`, `flagd`, `load-generator`, plus your added `tempo` and `loki`. Should NOT include `jaeger` or `opensearch` (you replaced them).
**If it's wrong:** a container stuck in `restarting` = usually a bad config mount or port clash. `docker compose logs <that-service> --tail 50` to see why.

## Check 2 — Shop works
**Do:** open http://localhost:8080 → add a product → Place Order.
**Expect:** order confirmation page with an order ID. This proves the whole gRPC call chain (frontend→cart→checkout→payment→shipping→email) is alive.
**If it's wrong:** if checkout fails now, a flag is probably stuck on. Check flagd — all variants should be `off`.

## Check 3 — Three datasources live in Grafana
**Do:** http://localhost:8080/grafana (or :3000) → Connections → Data sources.
**Expect:** Prometheus, Loki, Tempo all present. Click each → "Save & test" → green "datasource is working".
**If it's wrong:** red on Loki/Tempo = URL in the provisioning file points to the wrong container name/port. Should be `http://loki:3100` and `http://tempo:3200` (internal docker network names, not localhost).

## Check 4 — The correlation test (THE important one)
This is what everything downstream depends on: one trace_id must be findable in BOTH Tempo and Loki.
**Do:**
1. Grafana → Explore → Tempo → Search → pick a recent `checkout` trace → copy its trace_id.
2. Same trace visible as a span tree (you'll see frontend → checkout → payment etc.).
3. Switch to Loki → run `{service_name="checkout"} | trace_id="<that-id>"` (exact label name may differ — that's what you record in PROGRESS.md).
**Expect:** Loki returns log lines, and those lines carry the trace_id. Tempo shows the matching span tree.
**If it's wrong:**
- Loki empty for that trace_id but has logs otherwise → trace_id isn't being attached as a label/structured-metadata. This is the #1 Phase-1 trap. The collector's logs pipeline must preserve trace_id; Loki must have structured metadata enabled.
- Loki totally empty → collector's Loki exporter is misconfigured (wrong endpoint, OTLP not enabled on Loki). `curl http://localhost:3100/ready` should say `ready`.
- Tempo empty → collector still exporting to jaeger not tempo, or Tempo not receiving OTLP.

## Check 5 — Each scenario produces a visible effect + clean log
**Run each:** `python -m chaos.scenarios payment_failure --duration 90`
**Expect during run:**
- Terminal prints: flag set → waiting → flag reset.
- In Grafana (Prometheus): payment service error rate climbs during the window.
- After: `chaos/injected_events.log` has a new JSON line like:
  `{"scenario":"payment_failure","flag":"paymentFailure","start":"2026-...","end":"2026-..."}`
- Flag is back OFF afterward (verify in flagd UI at :8080/feature).
**Repeat for:** `queue_backlog` (kafka lag rises), `payment_outage` (checkout traces break / error), `overload` (ad or frontend latency rises).
**If it's wrong:**
- No visible effect → flag name is wrong (check against real `demo.flagd.json`) or hot-reload didn't pick up the file edit. Fallback: toggle via flagd UI and confirm the script at least logs correctly.
- Ctrl+C leaves a flag ON → the reset-on-exit handler isn't wired. Must fix — a stuck flag ruins later checks.

## Check 6 — Golden fixtures captured
**Expect:** `tests/fixtures/` contains `trace_sample.json`, `logs_sample.json`, `metrics_sample.json`, `flagd_flags.json`, all non-empty, all from real telemetry. PROGRESS.md notes which trace_id.

---
### Phase 1 is DONE when
All 6 checks pass AND PROGRESS.md "Verified facts" is filled: exact flag names, exact Loki trace_id label name, working Tempo query endpoint, exact Prometheus metric names for latency/error-rate/kafka-lag. **Do not start Phase 2 until Check 4 passes** — it's the foundation for the entire retrieval layer.
