# PHASE 3 — Infrastructure Analyst Agent (LangGraph) (Day 2)

Read CLAUDE.md + PROGRESS.md first. Depends on Phase 2 (retrieval + detector already built and working). All prompts and outputs in English.

> **Design shift from the original plan:** this is NOT just a bug-catcher. The product is an **infrastructure analyst copilot** that reads logs/traces/metrics — including resource utilization (CPU/memory), request/query rates, latency, and success logs — and answers ANY question about the system: failures, performance, right-sizing, capacity, "is this server over-provisioned?". Detecting the 4 chaos failures is one capability among several, not the whole point. The chat interface is the centerpiece.
>
> **Framing:** each Docker container = one running service with real CPU/memory limits (like a resource-capped server). We analyze real container resource metrics and give right-sizing / scaling / investigation advice. We do NOT pretend these are AWS EC2 instances — honest framing, still convincing.

## 3.0 Extra retrieval methods needed (small addition to Phase 2's `metric_client.py`)
The analyst needs resource data. Add these PromQL-backed methods (container metrics are already scraped by the demo's Prometheus via cAdvisor/node-exporter — read exact metric names from PROGRESS.md, don't guess):
- `get_cpu_usage(service, start, end) -> dict` — avg/peak CPU as a % of the container's CPU limit.
- `get_memory_usage(service, start, end) -> dict` — avg/peak memory bytes vs the container's memory limit.
- `get_resource_summary(start, end) -> list[dict]` — per service: cpu%, mem%, request_rate, p95_latency, error_rate. This one call powers most "how's the system / is X over-provisioned" questions.
If a metric name isn't available, degrade gracefully (return None for that field, note it) — never crash the whole answer over one missing metric.

## 3.1 LLM provider layer (`agents/llm.py`)
`complete(system, user, model_tier: "fast"|"smart", schema=None, enable_web_search=False)`:
- `LLM_PROVIDER` env:
  - **anthropic**: fast=`claude-haiku-4-5`, smart=`claude-sonnet-4-6`. If `schema` given, enforce via tool-use/structured output; if not, return free-form text (the analyst answer is natural language, not always JSON). If `enable_web_search`, attach the server-side web search tool and handle the multi-block loop. Verify current API usage at https://docs.claude.com before implementing.
  - **ollama**: both tiers=`OLLAMA_MODEL`; JSON mode + local validation with 1 retry when a schema is given; web search ignored (warn).
- Track per-call counters: calls, input/output tokens — exposed for the demo runner to print.

## 3.2 Schemas (`agents/schemas.py`)
```python
class Finding(BaseModel):
    """One structured observation the analyst extracted from telemetry."""
    category: Literal["error","performance","resource","capacity","healthy"]
    service: Optional[str] = None
    summary: str                          # one-line plain-English observation
    evidence: list[str]                   # concrete metric values / log lines it's based on
    severity: Literal["critical","warning","info"]

class Recommendation(BaseModel):
    action: str                           # concrete, reviewable step
    rationale: str
    risk_level: Literal["low","medium","high"]
    references: list[str] = []            # populated when web search used

class AnalystAnswer(BaseModel):
    """The complete answer to a question or alert."""
    answer: str                           # natural-language response shown to the user
    findings: list[Finding] = []
    recommendations: list[Recommendation] = []
    services_examined: list[str] = []
    requires_human_review: bool = True    # never auto-acts

class AgentState(BaseModel):
    trigger_type: Literal["alert","scheduled","user_question"]
    question: Optional[str] = None        # the user's natural-language question
    trace_id: Optional[str] = None
    time_range: Optional[tuple[str,str]] = None
    signals: list[dict] = []              # from Phase 2 detector, when present
    context: dict = {}                    # retrieved telemetry bundle (logs/traces/metrics/resource)
    answer: Optional[AnalystAnswer] = None
    loop_count: int = 0                   # hard cap 2
```

## 3.3 Context Builder (`agents/context_builder.py`) — pure Python, no LLM
Given the state, gather the RIGHT telemetry so the LLM has real data (never invents numbers). This is the key to a good demo — the LLM is only as good as what you feed it.
- If `trace_id`: fetch trace tree (TraceClient) + logs for that trace (LogClient) + metrics for the services in the trace.
- If `time_range` (or a question about "the system" / "last N minutes"): fetch `get_resource_summary()` + detector signals + recent ERROR/WARN logs (capped ~40 lines).
- If a question names a service ("is payment over-provisioned"): fetch that service's cpu/mem/rate/latency over a sensible window (default last 30 min) + its recent logs.
- Always attach any detector `signals` present — they are measured ground truth.
- Mask is already applied at the retrieval layer. Cap total context to stay token-sane (summarize metrics as numbers, don't dump raw series).
Output: a compact `context` dict the analyst prompt renders into text.

## 3.4 Analyst Agent (`agents/analyst.py`) — tier: smart, schema=AnalystAnswer
The single core agent. Fed the question + the context bundle. System prompt (use verbatim):
```
You are an Infrastructure Analyst copilot for a containerized microservice system (Astronomy Shop: frontend, cart, checkout, payment, shipping, currency, recommendation, ad, product-catalog; gRPC/HTTP; Kafka between checkout and accounting/fraud-detection). Each service runs in a container with CPU and memory LIMITS, like a resource-capped server.

You are given: the user's question (or an alert), plus a bundle of REAL telemetry — logs, trace spans, latency/error/request-rate metrics, and CPU/memory utilization vs limits. Detector signals, when present, are MEASURED facts you can fully trust.

Your job: answer the question directly and usefully in plain English, grounded ONLY in the provided telemetry. Cover whichever of these apply:
- FAILURES: if something is erroring or broken, explain what and likely why, and how to fix it.
- PERFORMANCE: latency, throughput, request rates, slowdowns, trends.
- RESOURCE / RIGHT-SIZING: is a service over- or under-provisioned? CPU/memory headroom vs limits. If a service sits far below its limits, say it's over-provisioned and suggest lowering limits; if near its limits, suggest scaling up or out.
- CAPACITY: headroom, "what saturates first if traffic grows", scaling advice.
- HEALTHY STATE: if everything is normal, SAY SO clearly with the numbers that show it — do not manufacture a problem.

Rules:
- Ground every claim in the provided numbers/logs. Quote concrete values in `evidence`. NEVER invent metrics you weren't given.
- If the data is insufficient to answer, say what's missing rather than guessing.
- Recommendations must be reviewable (config/scaling/code changes), never destructive (no data deletion, no uncontrolled restarts). requires_human_review is always true.
- risk_level reflects blast radius (adding monitoring = low; changing resource limits or core logic = medium/high).
- For unusual issues where you'd benefit from external best practices, you may use web search and cite sources in references.
- Be concise and specific. A tired on-call engineer should get the answer in seconds.

Return JSON matching the AnalystAnswer schema. The `answer` field is what the user reads; findings/recommendations are the structured backup.
```
- Set `enable_web_search=True` (anthropic) so it can look up best practices when useful.

## 3.5 Orchestrator (`agents/orchestrator.py`) — LangGraph
Keep it simple. Graph: `build_context → analyze → (needs_more_data && loop_count<2 → build_context) | persist`.
- `analyze` may signal it needs more data by returning an empty/low-content answer with a note; if so and loop_count<2, widen the context window once and retry. Hard-stop at 2. (Don't over-engineer the loop — a single retry is plenty for a demo.)
- `persist` node: append the full `AnalystAnswer` to `results/analysis_history.jsonl` + push one compact JSON log line to Loki (service="ai-copilot") so it shows in Grafana.
- Entry by `trigger_type`:
  - `user_question`: resolve target in code first — regex for a hex trace_id; else keep the question as-is and let context_builder pick a time window (default last 15 min). Return the answer directly.
  - `alert`: signals already provided by the scanner (a threshold breach). Build context around the alerting service/window, analyze, persist, (Phase 4) notify.
  - `scheduled`: run detector on the recent window first; no signals → exit with ZERO LLM calls. Signal → treat like `alert`.

## 3.6 Alert thresholds (extend Phase 2 detector config)
The detector already covers error/latency/queue/throughput. Add resource-based signals so alerts fire for the demo's "server needs upgrade" story (thresholds in `detection/config.yaml`):
- `cpu_high`: service CPU > 80% of its limit (sustained over the window).
- `memory_high`: service memory > 90% of its limit.
These make `adHighCpu` / `recommendationCacheFailure` scenarios trigger a resource alert that flows into the analyst → upgrade recommendation.

## Acceptance criteria
- [ ] `get_resource_summary()` returns real per-service CPU%/mem%/rate/latency from Prometheus.
- [ ] Ask "is payment over-provisioned?" on a normal system → analyst answers with real CPU/mem numbers and a right-sizing verdict (over/under/appropriate), grounded in the metrics.
- [ ] Ask "how is the system doing?" on a quiet system → analyst reports HEALTHY with supporting numbers, invents no problems.
- [ ] Run `adHighCpu` (overload) → resource alert fires (`cpu_high`) → analyst explains the CPU exhaustion and recommends scaling up/out, referencing the real utilization numbers.
- [ ] Ask about a real trace_id from a chaos run → analyst reads the trace + logs and explains what happened.
- [ ] All analyst outputs are schema-valid AnalystAnswer (1 retry on validation failure). The `answer` field is readable natural language.
- [ ] Web search fires when the analyst benefits from external best practice (anthropic mode); references populated. Ollama mode runs without crashing (no web search).
- [ ] Per-run LLM call/token counter prints.
