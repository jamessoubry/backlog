---
name: backlog
description: Process a backlog one item at a time — from a markdown file or a GitHub repo's issues. Implements each as a software feature using coder/tester/releaser subagents, then self-paces to the next item via ScheduleWakeup.
user_invocable: true
---

# /backlog

Work through a backlog one feature at a time. Each tick: pick the next item, implement it with subagents, mark it done, then schedule the next tick automatically.

## Arguments

Two modes:

**File mode** — markdown backlog file:
```
/backlog ~/main/backlog.md
/backlog ~/clawband/backlog.md
```

**GitHub issues mode** — repo's open issues labelled `backlog`, ordered by priority:
```
/backlog jamessoubry/clawband
/backlog jamessoubry/gavel
```

The argument is GitHub issues mode if it matches `owner/repo` (contains `/` but not a file path starting with `~` or `/`).

## File mode — backlog.md format

```markdown
- [ ] [project] Feature description
- [ ] [gavel] Add rate limiting to the public API
- [ ] [mund] Fix timeout in LangGraph orchestrator
- [x] [polybot] Already done — skipped
- [!] [gavel] Failed item — skipped, failure note inline
```

`[ ]` = pending · `[x]` = done · `[!]` = failed (both are skipped on future runs)

## GitHub issues mode — issue conventions

- Issues must have the `backlog` label to be queued
- Priority ordering: `P0` → `P1` → `P2` → unlabelled (within each priority, oldest issue first)
- State is tracked via labels and issue open/closed state:
  - Queued: open + `backlog` label
  - In progress: open + `backlog` + `in-progress` labels
  - Done: closed (backlog label removed)
  - Failed: open + `backlog` + `failed` label (stays open for manual retry/fix)
- The project is inferred from the repo name (e.g. `jamessoubry/clawband` → `clawband`)

## Project map

| Tag | Directory | Deploy | GitHub repo |
|-----|-----------|--------|-------------|
| `main` | `/home/ubuntu/main` | — | — |
| `mund` | `/home/ubuntu/mund` | `./deploy.sh` | — |
| `gavel` | `/home/ubuntu/gavel` | `./deploy.sh` | `jamessoubry/gavel` |
| `replenish` | `/home/ubuntu/replenish` | `./deploy.sh` | — |
| `filemover` | `/home/ubuntu/filemover` | CodeBuild via `./build.sh` | — |
| `polybot` | `/home/ubuntu/polybot` | `./deploy.sh --deploy` | — |
| `shortlink` | `/home/ubuntu/shortlink` | `./deploy.sh` | — |
| `oneeye` | `/home/ubuntu/oneeye` | CodeBuild via `./build.sh` | — |
| `clawband` | `/home/ubuntu/clawband` | `cargo build --release` + install | `jamessoubry/clawband` |

## Instructions

### Step 1 — Find the next item

**File mode:**
Read the file. Find the **first** line matching `- [ ]`.
If none exist: `bash ~/main/scripts/notify-main.sh "Backlog complete: all items in <filepath> processed"` then STOP — do NOT call ScheduleWakeup.

**GitHub issues mode:**
```bash
unset GITHUB_TOKEN
# Fetch open issues with backlog label, sorted by priority then issue number
ISSUE_JSON=$(gh issue list --repo "<owner/repo>" \
  --label backlog --state open --limit 100 \
  --json number,title,labels \
  --jq '
    def priority:
      .labels | map(.name) |
      if contains(["P0"]) then 0
      elif contains(["P1"]) then 1
      elif contains(["P2"]) then 2
      else 3 end;
    sort_by([priority, .number]) | .[0]
  ')
```
If result is null/empty: `bash ~/main/scripts/notify-main.sh "Backlog complete: no open backlog issues in <repo>"` then STOP.

Extract `ISSUE_NUMBER` and `ISSUE_TITLE` from the JSON.

### Step 2 — Schedule the next tick

Only reached if an item was found in Step 1. Call ScheduleWakeup now:
- `delaySeconds: 270`
- `prompt: "/backlog <same argument as current invocation>"` — file path or `owner/repo`

This ensures recovery if the session exhausts the rolling window mid-tick.

### Step 3 — Parse the item

**File mode:** extract `project` from `[tag]` and `feature` from the description.

**GitHub issues mode:** `project` = repo name (last segment of `owner/repo`). `feature` = issue title. `ISSUE_NUMBER` already set in Step 1.

### Step 4 — Trello: create or find card, move to In Progress

```bash
CARD_ID=$(python3 ~/backlog/trello.py card-find "<feature>")
if [ "$CARD_ID" = "NOT_FOUND" ]; then
  CARD_ID=$(python3 ~/backlog/trello.py card-create "<feature>" "<project>")
fi
python3 ~/backlog/trello.py card-move "$CARD_ID" in_progress
```

### Step 4b — GitHub issue: set in-progress label

**File mode:** look up `REPO` from the project map. If `—`, skip. Otherwise find or create an issue as before (search by feature title, create if not found). Then add `in-progress` label.

**GitHub issues mode:** `REPO` and `ISSUE_NUMBER` already known from Step 1. Just add the label:
```bash
unset GITHUB_TOKEN
gh issue edit "$ISSUE_NUMBER" --repo "$REPO" --add-label "in-progress"
```

Pass `ISSUE_NUMBER` and `REPO` into the workflow for coder and releaser.

### Step 5 — Read project context

Read `<project_dir>/CLAUDE.md` to understand architecture, build commands, test commands, and deploy pipeline before dispatching agents.

### Step 6 — Run the feature pipeline

Use the Workflow tool with three phases:

**Phase 1 — Implement** (label: `coder`)
- Agent reads the project codebase and implements the feature
- Makes targeted changes — no scope creep
- Writes or updates tests alongside the feature
- Commits with a clear message but does NOT push yet
- If `ISSUE_NUMBER` is set, append `Closes <REPO>#<ISSUE_NUMBER>` as a footer line in the commit message

**Phase 2 — Test** (label: `tester`)
- Before running tests: `python3 ~/backlog/trello.py card-move "$CARD_ID" test`
- Agent runs the project's test suite
- Verifies new tests pass and no regressions introduced
- If tests fail: return failure details, abort pipeline

**Phase 3 — Release** (label: `releaser`)
- Only runs if Test phase passed
- Pushes the commit (`git push`) — `unset GITHUB_TOKEN` first
- Runs deploy command if the project has one
- Confirms deployment succeeded
- Returns text containing "SUCCESS" on success, "FAILURE" on failure

### Step 7 — Update state, Trello, and GitHub

On success (all phases passed):
```bash
# File mode: mark done in file
- [ ] [project] feature  →  - [x] [project] feature

# Trello
python3 ~/backlog/trello.py card-move "$CARD_ID" done
python3 ~/backlog/trello.py card-comment "$CARD_ID" "✓ Released"

# GitHub (both modes — issue closed by Closes #N in commit, belt-and-braces explicit close)
unset GITHUB_TOKEN
gh issue close "$ISSUE_NUMBER" --repo "$REPO" \
  --comment "✓ Released" 2>/dev/null || true
# Remove in-progress label (close removes it implicitly but be explicit)
gh issue edit "$ISSUE_NUMBER" --repo "$REPO" \
  --remove-label "in-progress" --remove-label "backlog" 2>/dev/null || true
```

On failure (any phase failed):
```bash
# File mode: mark failed in file
- [ ] [project] feature  →  - [!] [project] feature — <one-line reason>

# Trello
python3 ~/backlog/trello.py card-move "$CARD_ID" blocked
python3 ~/backlog/trello.py card-comment "$CARD_ID" "✗ Failed: <reason>"

# GitHub (both modes — leave issue open, add failed label, remove in-progress)
unset GITHUB_TOKEN
gh issue comment "$ISSUE_NUMBER" --repo "$REPO" \
  --body "✗ Backlog pipeline failed: <reason>"
gh issue edit "$ISSUE_NUMBER" --repo "$REPO" \
  --add-label "failed" --remove-label "in-progress" 2>/dev/null || true
```

### Step 8 — Notify

```bash
bash ~/main/scripts/notify-main.sh "Backlog [project]: <feature> — ✓ released"
# or on failure:
bash ~/main/scripts/notify-main.sh "Backlog [project]: <feature> — ✗ failed: <reason>"
```

## Rate limit recovery

ScheduleWakeup is called at the very start (Step 2), before any work begins. If the session is killed mid-tick, the wakeup fires and retries. The pipeline is idempotent:
- File mode: item still `[ ]` → retry; `[x]`/`[!]` → skip
- GitHub issues mode: issue still open with `backlog` label → retry; closed or `failed` label skips naturally via the priority sort (failed items keep `backlog` label — manually remove it to drop from queue, or fix and remove `failed`)

## Constraints

- One item per tick — never process multiple items in one invocation
- Never deploy without passing tests — mark `[!]`/`failed` and move on if tests fail
- Always notify on every outcome (success or failure)
- One commit per feature item, never squash
