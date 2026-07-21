---
description: Run one chaos scenario end-to-end and report what the system detected
argument-hint: [scenario name: payment_failure | queue_backlog | payment_outage | overload]
allowed-tools: Bash, Read
---

Run the `$ARGUMENTS` scenario through the whole system and show me what happened, step by step. This is the core demo loop — I use it to sanity-check that detection + agents still work after changes.

Steps:
1. Confirm all flagd flags are currently OFF (a stuck flag pollutes the result). Reset if needed.
2. Run `python -m chaos.scenarios $ARGUMENTS --duration 90`.
3. Wait ~15s for telemetry to ingest (print a short countdown).
4. Run the detector over the scenario's time window and print the returned signals.
5. Run the full agent pipeline on that window and print, compactly:
   - signals → extraction (service, error_type, severity) → RCA (anomaly_type, confidence, first line of hypothesis) → fix (risk_level, first line, references) → LLM call/token counts.
6. State whether the result is directionally correct for this scenario, using the expected mapping:
   - payment_failure → service_failure
   - queue_backlog → message_loss
   - payment_outage → broken_trace or timeout
   - overload → resource_exhaustion or timeout
7. Confirm the flag was reset to OFF at the end.

If the anomaly_type is wrong, do NOT immediately rewrite prompts. First tell me what signal the RCA actually received — a wrong classification usually traces back to a wrong/missing signal upstream, not the prompt.
