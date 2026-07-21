---
description: End-of-session handoff — update PROGRESS.md so the next session can continue cleanly
allowed-tools: Bash(git status:*), Bash(git log:*), Edit, Read
---

We are ending this session. Update `PROGRESS.md` so a fresh session (with empty context) can pick up exactly where we left off. Do this carefully — the next session sees ONLY the files, not this conversation.

1. Run `git log --oneline -15` and `git status` to see what actually changed this session.
2. Update the status table in PROGRESS.md (mark phases done/in-progress).
3. Under "Decisions log", add any choice made this session that deviates from the PHASE files or CLAUDE.md (e.g. "used OpenSearch fallback instead of Loki because X", "renamed service in service_map to match real telemetry"). Be specific — these are easy to forget and expensive to rediscover.
4. Under "Known issues / TODO next session", write the exact next step and anything half-finished.
5. If this was Phase 1: make sure the "Verified facts" section is filled (flag names, Loki trace_id label, Tempo endpoint, Prometheus metric names) — later phases break without it.
6. Do NOT put anything critical only in your summary — put it in PROGRESS.md on disk. Summaries get lost; files do not.

Show me the diff of PROGRESS.md when done.
