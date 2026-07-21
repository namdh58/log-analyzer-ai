---
description: Run one chaos scenario end-to-end and show the analyst's answer
argument-hint: [scenario name: payment_failure | queue_backlog | payment_outage | overload]
allowed-tools: Bash, Read
---

Run the `$ARGUMENTS` scenario through the whole system and show me what happened, step by step. This is a sanity-check that detection + the analyst agent still work after changes.

Steps:
1. Confirm all flagd flags are currently OFF (a stuck flag pollutes the result). Reset if needed.
2. Run `python -m chaos.scenarios $ARGUMENTS --duration 90`.
3. Wait ~15s for telemetry to ingest (print a short countdown).
4. Run the detector over the scenario's time window and print the returned signals.
5. Trigger the analyst on that window (alert path) and print, compactly:
   - signals → the analyst `answer` (prose) → key findings (category, service, severity) → recommendations (action, risk_level, references) → LLM call/token counts.
6. Judge the result: is the answer GROUNDED (quotes real numbers/logs from the telemetry) and does it correctly relate to the injected problem for this scenario?
   - payment_failure → answer should identify payment service failing
   - queue_backlog → answer should identify Kafka publish flood / message backlog
   - payment_outage → answer should identify checkout→payment broken/unreachable
   - overload → answer should identify CPU/resource exhaustion + suggest scaling
7. Confirm the flag was reset to OFF at the end.

If the answer is wrong or invents numbers, do NOT immediately rewrite the prompt. First tell me what telemetry the context builder actually passed to the analyst — a bad answer usually means missing/wrong context, not a bad prompt.
