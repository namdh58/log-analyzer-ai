---
marp: true
theme: default
size: 16:9
paginate: true
footer: "AI Log Analysis Assistant — Technical Architecture Review"
---

<!-- _paginate: false -->

# AI Log Analysis Assistant
### Technical Architecture Review

How an infrastructure-analyst agent turns raw logs, traces, and metrics from a
live distributed system into a grounded root-cause answer.

*Internal design walkthrough — not a product demo.*

---

## Agenda

1. System architecture (layered)
2. Component / tech map
3. AI reasoning flow (core)
4. Log processing pipeline
5. Evidence collection & context
6. Retrieval strategy vs. vector RAG
7. Agent orchestration (LangGraph)
8. Deterministic detection layer
9. Multi-turn & reference resolution
10. Evidence → root cause
11. Recommendation generation
12. Request sequence, end to end
13. Chaos engineering validation
14. Expected AI output
15. Grounding safeguards
16. Takeaways

---

## System Architecture

Five layers. The LLM sits at the top of the stack, not underneath every step —
everything below it is plain, deterministic Python.

```
 Telemetry sources & collection
   OTel services → OTel Collector → Tempo / Loki (OTLP) / Prometheus
                        │
 Retrieval clients (Python, no LLM)
   log_client.py · metric_client.py · trace_client.py · PII masking
                        │
 Deterministic detection  ── zero LLM cost
   8 signal detectors (baseline + threshold)
                        │        measured, trusted signals
 AI reasoning  ── LangGraph + LLM
   resolve() → build_context() → analyze() → route()
                        │
 Interfaces
   Dashboard chat API · Grafana panels · scheduled scanner · chaos panel
```

---

## Component Map

| Component | Role |
|---|---|
| **Tempo** | Full span trees per trace_id — root cause of a broken flow |
| **Loki** | Native OTLP log ingestion — sometimes the *only* place a failure is visible |
| **Prometheus** | CPU/mem vs. container limits, latency, error & request rate |
| **Grafana** | Human-facing panels + embedded per-service view |
| **LangGraph** | The state graph run on every question |
| **Pluggable LLM** | Anthropic / DeepSeek / Ollama behind one `complete()` contract |
| **flagd** | The demo's own feature-flag service — real failure injection |
| **FastAPI** | Dashboard chat (8500) + chaos control panel (8600) |

---

## The AI Reasoning Flow (core)

Every question — user-typed, alert-triggered, or scheduled — runs this exact
nine-step chain:

```
1. User Question         /ask + optional conversation_id
        ↓
2. Evidence Collection    build_context() picks a retrieval mode
        ↓
3. Log Retrieval          Loki, incl. cross-service extras
        ↓
4. Metric Correlation     CPU/mem/latency/error vs. baseline
        ↓
5. Knowledge Retrieval     optional web search, external best practice
        ↓
6. Hypothesis Generation  LLM drafts Findings w/ quoted evidence
        ↓
7. Root Cause ID          answer names the cause, grounded only
        ↓
8. Recommendation         reviewable action + risk_level
        ↓
9. Final Answer           persisted, retried if too thin
```

---

## Log Processing Pipeline

From container stdout to a masked, queryable log line. Ingestion is standard
OTel — the only copilot-specific step is masking, applied once, at the exit of
the retrieval layer.

```
Emit     Auto-instrumented service containers
   ↓
Collect  OTel Collector — receives OTLP, fans out
   ↓
Store    Loki (logs) · Tempo (traces) · Prometheus (metrics)
   ↓
Mask     Regex PII masking — before anything leaves retrieval/
   ↓
Query    log_client.get_logs_by_time_range() / get_logs_by_trace_id()
```

---

## Evidence Collection & Context Construction

`build_context()` decides what evidence a question deserves — mode routing,
not a fixed query.

```
Question / trace_id / signals
        ↓
 Mode router: trace_id? named service(s)? none?
   ├── TRACE     → full span tree + logs by trace_id
   ├── SERVICE   → 1 service's metrics + logs + extras
   ├── SERVICES  → fresh metrics for every named service
   └── GENERAL   → fleet resource summary + error/warn logs
```

> **`_EXTRA_LOG_SERVICES`** — a "what's wrong with checkout?" question also
> pulls `frontend-proxy`'s and `payment`'s logs, because checkout's *own*
> telemetry never shows the real failure reason. Learned from a real
> investigation, not guessed.

---

## Retrieval Strategy: Not Vector RAG

"RAG" here means retrieval-augmented generation over **live typed telemetry**
— not embeddings over a document corpus. A considered rejection, not an
omission.

| Vector RAG — rejected | What this system does instead |
|---|---|
| Embed logs/metrics, retrieve by similarity | Typed queries straight against Loki / Prometheus / Tempo |
| Similarity search over 4 short turns adds latency for no benefit | Always current — fetched fresh at answer time |
| Follow-ups are sequential, not semantically clustered | Conversation memory = plain JSONL, last 4 turns, text only |
| Needs an extra vector-DB service | Deterministic mode-routing decides *what* to fetch |

> Recorded design decision: *"explicitly NOT a vector DB."*

---

## Agent Orchestration

One LangGraph state machine. User questions, alerts, and scheduled scans all
compile down to the same graph.

```
build_context() → analyze() → route() ─┬─→ persist()  (JSONL + Loki)
        ↑                              │
        └────────── retry() ←──────────┘
                (loop_count < 2, window × 2)
```

`route()` retries when the answer is under 40 characters with no findings —
the agent re-investigates with a wider window before admitting defeat.
Hard-capped at 2 retries.

---

## Deterministic Detection Layer

Eight signal checks, pure Python, zero LLM cost. The AI explains anomalies
this layer already measured.

| Signal | What it actually checks |
|---|---|
| `latency_spike` | p95 vs. baseline, requires ≥2 samples |
| `error_rate_spike` | absolute floor OR relative jump |
| `checkout_http_error_rate` | HTTP 5xx fallback — catches what span status can't |
| `span_gap` | trace tree diffed against expected service map |
| `queue_anomaly` | Kafka publish-rate vs. baseline (not consumer lag) |
| `throughput_drop` | request rate below a baseline ratio |
| `cpu_high` / `memory_high` | utilization vs. container *limit* |

---

## Multi-Turn Conversation

Memory resolves references. It never supplies facts. Two contexts,
intentionally never merged.

```
 💬 Conversation memory              📡 Fresh telemetry
 last 4 {question, summary}          fetched every turn by
 pairs — resolves pronouns           build_context()
 & follow-ups only                   the ONLY source for numbers
          └──────────┬──────────────────────┘
                      ↓
        analyze() — prompt forbids sourcing
             numbers from memory
```

**Cost-aware gate:** `needs_resolve()` is a regex heuristic — skip the LLM
entirely if the question already names a service, contains a trace ID, or has
no history yet. A fast-tier rewrite only runs for genuinely vague follow-ups.

---

## Evidence → Root Cause

The `Finding` schema every hypothesis must fit before becoming an answer:

| Field | Type | Meaning |
|---|---|---|
| `category` | enum | error · performance · resource · capacity · healthy |
| `service` | string? | which service this observation is about |
| `summary` | string | one-sentence observation |
| `evidence` | list[string] | quoted values that must exist in the fetched context |
| `severity` | enum | critical · warning · info |

The detector already found *that* something's wrong. The LLM's job is
narrower: turn several Findings into one causal sentence, with real numbers
in the `answer` field itself — not just pointers into findings.

---

## Recommendation Generation

Scored by blast radius, not urgency.

| Field | Type | Meaning |
|---|---|---|
| `action` | string | a reviewable config / scaling / code change |
| `rationale` | string | why, tied back to cited evidence |
| `risk_level` | enum | low · medium · high |
| `references` | list[string] | populated only when web search cited a source |

> `requires_human_review` is **always `true`**. The system prompt bars
> destructive actions outright — no data deletion, no uncontrolled restarts.
> The model is not trusted to self-certify safety; the schema enforces it.

---

## Request Sequence — End to End

```
User            → Dashboard API : POST /ask {question}
Dashboard API   → Orchestrator  : run(trigger=user_question)
Orchestrator    → Orchestrator  : resolve() — load last 4 turns, rewrite if vague
Orchestrator    → Context Builder : build_context(resolved question)
Context Builder → Retrieval Clients : fetch logs / metrics / traces, mode-routed
Retrieval Clients → Context Builder : real telemetry rows
Context Builder → Analyst LLM   : rendered context + question
Analyst LLM     → Orchestrator  : AnalystAnswer (grounded JSON)
Orchestrator    → User          : answer + findings + recommendations
```

---

## Chaos Engineering Validation

Every scenario is a built-in flagd feature flag from the OpenTelemetry Demo
itself — no custom fault-injection code.

| Scenario | flagd flag | Real effect | Signal caught |
|---|---|---|---|
| payment_failure | `paymentFailure → 100%` | cards decline; span status never flips to ERROR | HTTP 5xx fallback |
| payment_outage | `paymentUnreachable → on` | payment unreachable mid-trace | span_gap + error_rate_spike |
| queue_backlog | `kafkaQueueProblems → on` | ~35× publish flood, duplicate writes; lag stays 0 | queue_anomaly |
| overload | `adHighCpu → on` | ad service CPU saturates (~400% peak) | cpu_high + latency_spike |

Every AI answer during development was cross-checked directly against live
Prometheus/Loki queries — the same evidence-first standard the system holds
itself to.

---

## Expected AI Output

```json
{
  "answer": "payment averages 0.4% CPU, 80.6% memory (113/140MiB) → over-provisioned on CPU, near its memory limit.",
  "findings": [
    { "category": "resource", "service": "payment", "severity": "info",
      "evidence": ["cpu avg=0.4%", "mem avg=80.6% (113/140MiB)"] }
  ],
  "recommendations": [
    { "action": "lower payment's CPU limit", "risk_level": "low" }
  ],
  "services_examined": ["payment"],
  "requires_human_review": true
}
```

Every number here is the kind that must trace back to a fetched telemetry row.

---

## Grounding Safeguards

Every fix below lives in retrieval code, never in a prompt tweak.

- 🧩 **Cross-service log mapping** — pull the services where the real reason lives
- 📏 **Per-service log capping** — no service can crowd out another's evidence
- 🔁 **Fresh data per comparison** — every named service gets live metrics
- 🧠 **Reference-only memory** — history resolves pronouns, never supplies numbers
- 💸 **Cost-gated resolution** — LLM rewrite only for genuinely ambiguous follow-ups
- 📐 **Labeled rows, not raw JSON** — fixed a real cross-service misattribution bug

---

## Takeaways

**01 — Deterministic where possible**
Detection is pure Python and free to run. The LLM is reserved for the one step
that actually needs reasoning: synthesis.

**02 — Retrieval is the product**
Grounding lives in `build_context()`, not the prompt. Mode-routing,
cross-service mapping, and per-service capping do the real anti-hallucination
work.

**03 — Validated against ground truth**
Every claim the AI makes at runtime is checked against real Loki/Prometheus/
Tempo data — not asserted.
