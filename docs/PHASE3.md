# PHASE 3 — Multi-Agent System (LangGraph) (Day 2)

Read CLAUDE.md + PROGRESS.md first. Depends on Phase 2. All prompts and outputs in English.

## 3.1 LLM provider layer (`agents/llm.py`)
Single entry point used by all agents:
`complete_structured(system: str, user: str, schema: type[BaseModel], model_tier: "fast"|"smart", enable_web_search: bool=False) -> BaseModel`
- Provider from `LLM_PROVIDER` env:
  - **anthropic**: fast=`claude-haiku-4-5`, smart=`claude-sonnet-4-6`. Enforce schema via tool-use/structured output. If `enable_web_search`, attach the server-side web search tool (`web_search_20250305`) and handle the multi-block response loop. Verify exact current API usage against https://docs.claude.com before implementing.
  - **ollama**: both tiers=`OLLAMA_MODEL`, JSON mode + local schema validation with 1 retry on parse failure. `enable_web_search` is silently ignored (log a warning).
- Track per-pipeline counters: calls, input/output tokens (anthropic) — exposed for run_demo.py to print.

## 3.2 Schemas (`agents/schemas.py`)
```python
class ErrorExtraction(BaseModel):
    trace_ids: list[str]; services: list[str]; timestamp: str
    error_type: str                       # short snake_case label; "unclassified_error" if unclear
    severity: Literal["critical","warning","info"]
    raw_log_snippets: list[str]           # verbatim, max 5
    related_span_ids: list[str]

class RootCauseAnalysis(BaseModel):
    hypothesis: str; confidence: float    # 0.0-1.0
    evidence: list[str]; affected_services: list[str]
    anomaly_type: Literal["service_failure","message_loss","broken_trace",
                          "resource_exhaustion","timeout","unknown"]
    needs_more_data: bool
    missing_data_request: Optional[str] = None   # e.g. "logs from checkout service 10:00-10:05"

class FixRecommendation(BaseModel):
    recommendation: str; references: list[str]
    risk_level: Literal["low","medium","high"]
    requires_human_review: bool = True    # ALWAYS true, system never auto-fixes

class AgentState(BaseModel):
    trigger_type: Literal["alert","scheduled","user_question"]
    trace_id: Optional[str] = None
    time_range: Optional[tuple[str,str]] = None
    question: Optional[str] = None
    signals: list[dict] = []
    extraction: Optional[ErrorExtraction] = None
    rca: Optional[RootCauseAnalysis] = None
    fix: Optional[FixRecommendation] = None
    loop_count: int = 0                   # hard cap 2
```

## 3.3 Error Extractor (`agents/error_extractor.py`) — tier: fast
Pre-processing in Python BEFORE the LLM call: fetch logs (by trace_id or window), keep only ERROR/WARN, cap at 50 lines; also fetch span-tree summary for up to 3 affected traces (service names + status + duration only, not full spans). If a loop iteration set `missing_data_request`, adjust the fetch accordingly (parse service/time hints from it in code; simple heuristics are fine).

System prompt (use verbatim):
```
You are the Error Extractor agent in a distributed-observability copilot.
Input: pre-filtered ERROR/WARN log lines (PII already masked) and compact span summaries from a microservice system. Detector signals may be attached as trusted measured facts.
Task: extract WHAT failed, precisely and structurally. Do NOT infer root cause (a later agent does that).
Rules:
- error_type: short snake_case label from log content (e.g. connection_timeout, charge_failed, consumer_lag). Use "unclassified_error" if unclear — never guess.
- raw_log_snippets: copy the most relevant lines VERBATIM (max 5). Never paraphrase, never invent content absent from the input.
- If multiple distinct errors exist, report the highest-severity one.
Return ONLY JSON matching the provided schema.
```

## 3.4 Root Cause Analyzer (`agents/root_cause_analyzer.py`) — tier: smart
Input: extraction + detector signals + relevant metrics (baseline vs current).

System prompt (use verbatim):
```
You are the Root Cause Analyzer agent for a microservice e-commerce system (Astronomy Shop: frontend, cart, checkout, payment, shipping, email, currency, recommendation, ad, product-catalog; gRPC/HTTP calls; Kafka between checkout and accounting/fraud-detection).
Input: (1) structured error extraction, (2) detector signals — these are MEASURED values, treat as reliable ground truth, (3) metrics with baselines.
Task: produce one clear root-cause hypothesis in plain English.
Anomaly types: service_failure (a service errors on requests), message_loss (queue messages delayed/lost, consumer lag), broken_trace (a call chain never completes; missing child spans), resource_exhaustion (overload → rising latency, possible cascade), timeout, unknown. Use "unknown" with a detailed hypothesis rather than forcing a bad fit.
Rules:
- Ground the hypothesis in signals first, logs second. Do not classify from raw text alone if no signal supports it.
- Multiple simultaneous signals may be one cascading cause, not independent failures — say so if likely.
- confidence: high only with multiple agreeing signals + clear logs; low for single weak signal.
- evidence: concrete items quoted/derived from input only. Never fabricate.
- If confidence < 0.5 or key data is missing, set needs_more_data=true and state exactly what is needed in missing_data_request (service + time range).
Return ONLY JSON matching the provided schema.
```

## 3.5 Fix Recommendation (`agents/fix_recommendation.py`) — tier: smart, `enable_web_search=True` (anthropic only)
System prompt (use verbatim):
```
You are the Fix Recommendation agent. Input: a root-cause analysis for a microservice failure.
Task: propose a concrete, reviewable remediation.
Rules:
- Common types (service_failure, message_loss, timeout, resource_exhaustion): answer from known best practices (e.g. message_loss → manual acks + consumer scaling + DLQ; resource_exhaustion → autoscaling/rate limiting/caching; timeout → budgets + retries with backoff + circuit breaker).
- For complex or "unknown" cases, use web search if available and cite sources in references.
- This system only RECOMMENDS. requires_human_review is always true. Never propose destructive actions (data deletion, uncontrolled restarts) — only reviewable code/config changes.
- State any assumptions about system specifics you cannot know.
- risk_level reflects blast radius of the proposed change (observability additions=low; core-path logic changes=medium/high).
Return ONLY JSON matching the provided schema.
```

## 3.6 Orchestrator (`agents/orchestrator.py`) — LangGraph
Graph: `extract → analyze → (needs_more_data && loop_count<2 → extract) | recommend → persist`.
- `persist` node: append full result to `results/rca_history.jsonl` + push one JSON log line to Loki (service="ai-copilot"). (Teams notify hook added in Phase 4 as optional.)
- Entry by `trigger_type`:
  - `alert`: signals already provided (from scanner) → full pipeline.
  - `scheduled`: run `SignalDetector.detect()` on the window first; no signals → exit without any LLM call.
  - `user_question`: resolve target in code first — regex for a hex trace_id in the question; else one fast-tier LLM call to parse `{trace_id | time_range}`; then run pipeline and return result directly.

## Acceptance criteria
- [ ] payment_failure scenario → pipeline outputs anomaly_type `service_failure`, confidence > 0.6.
- [ ] queue_backlog → `message_loss`; payment_outage → `broken_trace` or `timeout`; overload → `resource_exhaustion` (hypotheses must reference the injected problem).
- [ ] Loop mechanism: forced `needs_more_data=true` re-enters extract with adjusted fetch, hard-stops at loop_count=2.
- [ ] All agents return schema-valid JSON on every run (add 1 retry on validation failure).
- [ ] Web search fires for a forced `unknown` case (anthropic mode) and references are populated.
- [ ] `LLM_PROVIDER=ollama` runs the same pipeline end-to-end without code changes (quality may be lower — just must not crash).
- [ ] Per-run LLM call/token counter prints correctly.
