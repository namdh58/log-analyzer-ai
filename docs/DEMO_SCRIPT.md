# Demo Script — AI Copilot Chat, 4 Chaos Cases

Presenter's cue card. Chat with the copilot in the dashboard (`$DASHBOARD_URL`, default `http://localhost:8500`). Run each `chaos.scenarios` command in a **second terminal** so the chat stays free to use.

General pattern per case: **trigger chaos → ask primary question → ask follow-up(s) → let the flag auto-reset → move on.**

---

## 0. Intro — system is healthy (no chaos yet)

Warm up the audience on ordinary questions, before anything is broken.

1. "How is the system doing right now?"
2. "Is the payment service over-provisioned?"
3. "If traffic tripled, which service saturates first?"

> Cue: this establishes the copilot answers *any* infra question, not just "what's on fire" — sets up the contrast for the chaos cases below.

---

## 1. payment_failure — payment service fails charge requests

**What it is:** `paymentFailure` flag → 100% of charge requests fail with an "Invalid token" error, inside the `payment` service.
**Expected signal:** `error_rate_spike` → anomaly_type `service_failure`.

**Trigger:**
```
python3 -m chaos.scenarios payment_failure --duration 120
```

**Primary question** (ask ~20-30s after triggering, once a checkout has had time to fail):
> "What's wrong with checkout right now?"

**Follow-ups:**
> "Which trace_id shows this failure?"
> "What should I do to fix it?"

> Cue: point out the answer names `payment` specifically and quotes the real error text — not a generic "something's wrong."

---

## 2. payment_outage — payment service unreachable

**What it is:** `paymentUnreachable` flag → payment service becomes completely unreachable (connection-level, not an application error).
**Expected signal:** `span_gap` + `error_rate_spike` → anomaly_type `broken_trace` / `timeout`.

**Trigger:**
```
python3 -m chaos.scenarios payment_outage --duration 120
```

**Primary question:**
> "Anything abnormal in the last few minutes?"

**Follow-ups:**
> "Is this the same kind of payment problem as before, or something different?"
> "How would you fix this one?"

> Cue: the whole point of this case — the answer should describe a *span gap / timeout*, not a clean error message, contrasting directly with case 1's application-level failure. If the copilot can't tell the two apart, that's worth calling out live rather than glossing over.

---

## 3. queue_backlog — Kafka queue overload + consumer lag

**What it is:** `kafkaQueueProblems` flag → floods the Kafka queue while adding consumer-side delay, causing lag to spike.
**Expected signal:** `queue_anomaly` (publish flood) → anomaly_type `message_loss`.

**Trigger:**
```
python3 -m chaos.scenarios queue_backlog --duration 120
```

**Primary question:**
> "Is the checkout queue backing up?"

**Follow-ups:**
> "Are we at risk of losing messages if this keeps going?"
> "Is this a capacity issue or a bug?"

> Cue: this is the one case where nothing is "erroring" — it's a backlog/lag pattern, good moment to show the copilot reasoning about degradation, not just failures.

---

## 4. overload — high CPU load in ad service

**What it is:** `adHighCpu` flag → triggers artificial high CPU load inside the `ad` service.
**Expected signal:** `latency_spike` (+ possible `throughput_drop`) → anomaly_type `resource_exhaustion`.

**Trigger:**
```
python3 -m chaos.scenarios overload --duration 120
```

**Primary question:**
> "The ad service just alerted — what's happening and what should I do?"

**Follow-ups:**
> "Is this a code bug or a resource/capacity problem?"
> "Should we scale this service or fix something in the code?"

> Cue: land the "infra analyst, not just detector" pitch — this answer should talk in terms of CPU vs. limits and a scaling recommendation, not just "ad service is slow."

---

## Wrap-up

> "Now that you've seen all that — is the system over-provisioned or under-provisioned anywhere, based on everything that just happened?"

> Cue: closing line reinforcing the core pitch (CLAUDE.md Product framing): this is a capacity/right-sizing copilot that *also* handles the 4 failure cases — not the other way around.

---

## Timing notes
- Real checkout traffic is sparse (~1 order every 30-40s). Use `--duration 120` (not 60) so the injection window reliably contains at least one affected request — a shorter window can catch zero requests and give a false "nothing happened."
- Flags auto-reset when the scenario's duration elapses (`chaos/scenarios.py`) — no manual cleanup needed between cases, but leave ~15-20s after each reset before starting the next case so signals from the previous one don't bleed into the next detection window.
