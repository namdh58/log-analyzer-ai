---
description: Start work on a project phase (reads memory, works acceptance criteria in order)
argument-hint: [phase number, e.g. 2]
---

Start a work session on Phase $ARGUMENTS of this project.

Steps:
1. Read `CLAUDE.md` and `PROGRESS.md` in full first. Pay special attention to the "Verified facts" section — later phases depend on the exact flag names, Loki labels, Tempo endpoint, and Prometheus metric names recorded there. Never guess these from memory.
2. Read `docs/PHASE$ARGUMENTS.md` — that is the spec for this session.
3. Confirm the previous phase's status in PROGRESS.md is done. If it is not, stop and tell me which prerequisite is missing before writing any code.
4. Work through the acceptance criteria in `docs/PHASE$ARGUMENTS.md` IN ORDER. For deterministic code (retrieval, masking, detection, schemas), write a test with concrete expected values, run it, and self-fix until green before moving to the next criterion. Show me the passing test output.
5. `git commit` after each acceptance criterion passes, with a short conventional message.
6. Keep debug output small: `docker compose logs <svc> --tail 50`, `curl ... | head -30`, `jq` to extract only needed fields. Never dump full container logs or full JSON API responses into the conversation.
7. Do NOT try to complete more than this one phase. When the phase's acceptance criteria are met, stop and run `/handoff`.

Begin now.
