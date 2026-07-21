# EXPECTED OUTPUT — Phase 3 (Infrastructure Analyst Agent)

Two kinds of checks: schema-valid JSON (deterministic — self-fixable) and answer quality (you read the answer and judge if it's grounded + useful). The analyst's `answer` field is natural language — judge it like a human would judge an on-call engineer's reply.

---

## Check 1 — Resource metrics are real
**Run:** `get_resource_summary(last_15_min)` and print it.
**Expect:** one row per service with real numbers — cpu%, mem%, request_rate, p95_latency, error_rate. Values plausible (idle services low CPU, load-genned services higher).
**If it's wrong:** all zeros/None → PromQL metric names wrong. `curl http://localhost:9090/api/v1/label/__name__/values | jq` and grep for `container_cpu`, `container_memory`, `container_spec` — cAdvisor-style names. Record the working names in PROGRESS.md.

## Check 2 — Right-sizing question (THE new core capability)
**Ask:** "is payment over-provisioned?" on a normal system.
**Expect:** an answer that quotes real CPU/mem numbers vs the limit and gives a verdict — e.g. "payment averages 12% CPU, 80/300MiB memory → over-provisioned, could lower limits". `findings` has a `resource`/`capacity` category entry; `recommendations` has a concrete right-sizing action with risk_level.
**If it's wrong:**
- Made-up numbers not matching Prometheus → context_builder didn't fetch resource metrics for that service, so the LLM invented them. Fix the builder to include `get_resource_summary`/`get_memory_usage` for the named service. (The LLM inventing numbers = context problem, not prompt problem.)
- Vague "seems fine" with no numbers → not enough data reached the agent; check what context was passed in.

## Check 3 — Healthy-state honesty
**Ask:** "how is the system doing?" on a quiet system (no chaos).
**Expect:** clearly says the system is HEALTHY, backs it with numbers (request rate steady, low error rate, latency normal, resource headroom). Does NOT manufacture a problem.
**If it's wrong:** invents a fake issue → the prompt's "if healthy, say so" rule isn't landing, or a stale signal from an earlier chaos run leaked into context. Confirm the window is genuinely quiet and no old signals are attached.

## Check 4 — Resource alert → upgrade recommendation (the demo money shot)
**Run:** `adHighCpu` (overload) scenario, let it run, then trigger the analyst on that window (via alert path).
**Expect:** `cpu_high` signal fired; analyst explains ad/target service is CPU-saturated (real % near limit), recommends scaling up (raise CPU limit) or out (add replica), references the actual utilization and request rate.
**If it's wrong:**
- No `cpu_high` signal → resource threshold not added to detector config, or CPU metric not read. See Check 1.
- Explains it as an error not a resource issue → the resource signal/metrics weren't in context; the analyst defaulted to log-based reasoning.

## Check 5 — Trace question still works
**Ask:** "anything wrong with trace <real id from a chaos run>?"
**Expect:** analyst reads the span tree + logs and explains what happened on that trace. (This is the original capability — must still work.)
**If it's wrong:** can't find trace → trace_id regex/parse failed; test on the actual question string.

## Check 6 — Schema validity + provider swap
**Expect:** every run returns a valid AnalystAnswer, `answer` is readable prose (not raw JSON dumped into the field). `LLM_PROVIDER=ollama` completes without crashing (quality lower, may miss nuance, no web search — all acceptable).
**If it's wrong:** parse errors → 1-retry-on-validation not wired, or (anthropic) use tool-use structured output instead of parsing free text.

## Check 7 — Web search + cost counter
**Expect:** for a question benefiting from best practices (e.g. "how should I fix recurring Kafka consumer lag?"), web search fires (anthropic) and references appear. After each run a line prints: `LLM calls: N | in: X tok | out: Y tok`.

---
### Phase 3 is DONE when
Checks 1, 5, 6, 7 pass mechanically, and Checks 2, 3, 4 read as genuinely useful, grounded answers to YOU across a couple of tries. The bar: would an on-call engineer trust this answer? The single most important thing to get right is Check 2's grounding — the analyst must quote REAL numbers, never invent them. If it invents numbers, fix the context builder (feed it the data), not the prompt.
