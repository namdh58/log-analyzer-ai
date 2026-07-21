# EXPECTED OUTPUT — Phase 3 (Agents)

Two kinds of checks here: schema-valid JSON (deterministic — self-fixable) and anomaly classification (LLM judgment — you review a table, you don't hard-assert).

---

## Check 1 — Each agent returns schema-valid JSON
**Run:** each agent once with fixture input.
**Expect:** a valid Pydantic object every time, no parse errors. Extractor → `ErrorExtraction`, RCA → `RootCauseAnalysis`, Fix → `FixRecommendation`.
**If it's wrong:** model returned prose or broken JSON → the 1-retry-on-validation-failure isn't wired, or the prompt's "ONLY JSON" rule is being ignored. For anthropic, use tool-use/structured output (schema-enforced) rather than parsing free text.

## Check 2 — The classification table (THE check you personally review)
**Run:** all 4 scenarios through the full pipeline. Print this table:

```
scenario         | anomaly_type        | confidence | hypothesis (first line)
-----------------|---------------------|-----------|------------------------
payment_failure  | service_failure     | 0.8x      | Payment service is rejecting charge requests...
queue_backlog    | message_loss        | 0.7x      | Kafka consumer lag is growing, messages delayed...
payment_outage   | broken_trace        | 0.7x      | checkout→payment call never completes...
overload         | resource_exhaustion | 0.6x      | Ad/frontend latency rising under load...
```

**Expect (directional, not exact):**
| scenario | anomaly_type should be | confidence |
|---|---|---|
| payment_failure | `service_failure` | > 0.6 |
| queue_backlog | `message_loss` | > 0.5 |
| payment_outage | `broken_trace` or `timeout` | > 0.5 |
| overload | `resource_exhaustion` or `timeout` | > 0.5 |

And the hypothesis text must clearly reference the actual injected problem (mentions payment / kafka-queue / broken-call / overload). Confidence exact value doesn't matter — direction does.
**If it's wrong:**
- Wrong anomaly_type → usually the signal from Phase 2 was wrong or wasn't passed in. Check what signals the RCA actually received (log the AgentState going in). The RCA prompt says trust signals first — so a wrong signal = wrong answer. Fix upstream, not the prompt.
- Right type but confidence always 0.99 or always 0.3 → prompt calibration; tune the confidence guidance, but this is low priority for a demo.
- Hypothesis generic/hand-wavy → not enough evidence reaching the agent; check the pre-filter is passing real log snippets + metrics.

## Check 3 — Loop mechanism works and terminates
**Run:** a test that forces RCA to return `needs_more_data=true` (mock it).
**Expect:** Orchestrator goes back to `extract` with adjusted fetch, and HARD-STOPS at `loop_count=2` — never infinite. Print loop_count at each pass.
**If it's wrong:** loops forever → the `loop_count < 2` guard in the conditional edge is missing/wrong. Increments but never re-fetches differently → `missing_data_request` isn't being read by the extractor.

## Check 4 — Web search fires on unknown (anthropic mode only)
**Run:** force an `anomaly_type: unknown` case through Fix agent.
**Expect:** the web search tool is actually called, and `references` in the output contains real URLs.
**If it's wrong:** no references / no search → the web_search tool isn't attached, or the multi-block response loop isn't handled (model asks to search but you never feed the result back). In `ollama` mode this is EXPECTED to be skipped — a warning log, empty references, that's fine.

## Check 5 — Cost counter
**Expect:** after each pipeline run, a printed line like `LLM calls: 3 | input tokens: 4200 | output tokens: 610`.
**If it's wrong:** counter not incremented in the llm.py wrapper.

## Check 6 — Ollama mode doesn't crash
**Run:** `LLM_PROVIDER=ollama` full pipeline once.
**Expect:** completes end-to-end, valid schema out (quality may be worse, classification may be wrong — that's OK). No crash, no code change needed to switch providers.
**If it's wrong:** crash on switch → provider abstraction leaks (agent hardcodes an anthropic-only call somewhere).

---
### Phase 3 is DONE when
Checks 1,3,4,5,6 pass mechanically, and Check 2's table looks directionally right to YOU across all 4 scenarios (3/4 correct is acceptable for a demo — note the weak one). Remember: don't chase perfect LLM answers by over-editing prompts. If the signal is right and the hypothesis names the real problem, ship it.
