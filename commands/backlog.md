---
name: backlog
description: Process a markdown todo list one item at a time, implementing each as a software feature using coder/tester/releaser subagents, then self-pacing to the next item via ScheduleWakeup.
user_invocable: true
---

# /backlog

Work through a markdown todo list one feature at a time. Each tick: pick the first unchecked item, implement it with subagents, mark it done, then schedule the next tick automatically.

## Arguments

`/backlog <filepath>` — e.g., `/backlog ~/main/todo.md`

## Todo file format

```markdown
- [ ] [project] Feature description
- [ ] [gavel] Add rate limiting to the public API
- [ ] [mund] Fix timeout in LangGraph orchestrator
- [x] [polybot] Already done — skipped
- [!] [gavel] Failed item — skipped, failure note inline
```

`[ ]` = pending · `[x]` = done · `[!]` = failed (both are skipped on future runs)

## Project map

| Tag | Directory | Deploy |
|-----|-----------|--------|
| `main` | `/home/ubuntu/main` | — |
| `mund` | `/home/ubuntu/mund` | `./deploy.sh` |
| `gavel` | `/home/ubuntu/gavel` | `./deploy.sh` |
| `replenish` | `/home/ubuntu/replenish` | `./deploy.sh` |
| `filemover` | `/home/ubuntu/filemover` | CodeBuild via `./build.sh` |
| `polybot` | `/home/ubuntu/polybot` | `./deploy.sh --deploy` |
| `shortlink` | `/home/ubuntu/shortlink` | `./deploy.sh` |
| `oneeye` | `/home/ubuntu/oneeye` | CodeBuild via `./build.sh` |
| `clawband` | `/home/ubuntu/clawband` | `cargo build --release` + install |

## Instructions

### Step 1 — Read the file

Read the file at the path given in the arguments. Find the **first** line matching `- [ ]`.

If no `[ ]` items exist:
- Run `bash ~/main/scripts/notify-main.sh "Backlog complete: all items in <filepath> processed"`
- Stop. Do NOT call ScheduleWakeup — the list is empty and scheduling would create an infinite loop.

### Step 2 — Schedule the next tick

Only reached if a `[ ]` item was found in Step 1. Call ScheduleWakeup now:
- `delaySeconds: 270`
- `prompt: "/backlog <filepath>"` — same file path as the current invocation

This ensures recovery if the session exhausts the rolling window mid-tick. The next wakeup
will re-read the file; if the current item is still `[ ]` it was not completed and will be
retried. If it was already marked `[x]` or `[!]`, it will be skipped.

### Step 3 — Parse the item

Extract:
- `project` — from `[tag]` in the item text, or infer from the description
- `feature` — the description after the tag

### Step 4 — Trello: create or find card, move to In Progress

```bash
# Find existing card (in case of retry)
CARD_ID=$(python3 ~/backlog/trello.py card-find "<feature>")
if [ "$CARD_ID" = "NOT_FOUND" ]; then
  CARD_ID=$(python3 ~/backlog/trello.py card-create "<feature>" "<project>")
fi
# Move to In Progress
python3 ~/backlog/trello.py card-move "$CARD_ID" in_progress
```

### Step 5 — Read project context

Read `<project_dir>/CLAUDE.md` to understand architecture, build commands, test commands, and deploy pipeline before dispatching agents.

### Step 6 — Run the feature pipeline

Use the Workflow tool with three phases:

**Phase 1 — Implement** (label: `coder`)
- Agent reads the project codebase and implements the feature
- Makes targeted changes — no scope creep
- Writes or updates tests alongside the feature
- Commits with a clear message but does NOT push yet

**Phase 2 — Test** (label: `tester`)
- Before running tests: `python3 ~/backlog/trello.py card-move "$CARD_ID" test`
- Agent runs the project's test suite
- Verifies new tests pass and no regressions introduced
- If tests fail: return failure details, abort pipeline

**Phase 3 — Release** (label: `releaser`)
- Only runs if Test phase passed
- Pushes the commit (`git push`)
- Runs deploy command if the project has one
- Confirms deployment succeeded
- Returns text containing "SUCCESS" on success, "FAILURE" on failure

### Step 7 — Update the file and Trello

On success (all phases passed):
```
- [ ] [project] feature  →  - [x] [project] feature
python3 ~/backlog/trello.py card-move "$CARD_ID" done
python3 ~/backlog/trello.py card-comment "$CARD_ID" "✓ Released"
```

On failure (any phase failed):
```
- [ ] [project] feature  →  - [!] [project] feature — <one-line reason>
python3 ~/backlog/trello.py card-move "$CARD_ID" blocked
python3 ~/backlog/trello.py card-comment "$CARD_ID" "✗ Failed: <reason>"
```

### Step 8 — Notify

```bash
bash ~/main/scripts/notify-main.sh "Backlog [project]: <feature> — ✓ released"
# or on failure:
bash ~/main/scripts/notify-main.sh "Backlog [project]: <feature> — ✗ failed: <reason>"
```

## Rate limit recovery

ScheduleWakeup is called at the very start of each tick (Step 1), before any work begins.
This means a next-tick wakeup is always queued, even if the current tick is killed mid-flight
by an exhausted rolling window. On recovery the file is re-read fresh; incomplete items
(still `[ ]`) are retried, completed items (`[x]`/`[!]`) are skipped. The pipeline is
idempotent by design.

## Constraints

- One item per tick — never process multiple items in one invocation
- Never deploy without passing tests — mark `[!]` and move on if tests fail
- Always notify on every outcome (success or failure)
- One commit per feature item, never squash
