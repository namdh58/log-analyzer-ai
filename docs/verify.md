---
description: Verify a phase against its EXPECTED checklist and report pass/fail per check
argument-hint: [phase number, e.g. 1]
allowed-tools: Bash, Read
---

Verify Phase $ARGUMENTS against its acceptance checklist. Read `docs/EXPECTED-PHASE$ARGUMENTS.md` and run each check that can be run programmatically (health checks, curls, tests, pipeline runs). Do NOT modify code in this command — this is verification only.

For each check, report one line: `CHECK n: PASS/FAIL — <what you observed>`. If FAIL, quote the matching "If it's wrong" hint from the EXPECTED file and name the most likely cause, but do not fix it yet — wait for me.

Rules:
- Keep output tiny: pipe/limit everything (`--tail`, `head`, `jq`). Do not flood the conversation.
- For checks that require my eyes (a Grafana screen, the shop UI), say `CHECK n: MANUAL — <exactly what I should look at and what a pass looks like>` instead of guessing.
- End with a summary line: `Phase $ARGUMENTS: X/Y automated checks passed, Z need manual verification.`

Some checks depend on running a chaos scenario first (e.g. detector/agent checks). If so, run the relevant `python -m chaos.scenarios <name>` yourself, wait for ingest, then verify.
