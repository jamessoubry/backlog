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

**No-argument mode** — if no argument is provided, look for a `.backlog.yml` in the current working directory. If found and it contains a `repo:` field, use that as the `owner/repo` argument automatically. If no `.backlog.yml` or no `repo:` field, print usage and stop.

## File mode — backlog.md format

```markdown
- [ ] [project] Feature description
- [ ] [gavel] Add rate limiting to the public API
- [ ] [mund] Fix timeout in LangGraph orchestrator
- [x] [polybot] Already done — skipped
- [!] [gavel] Failed item — PR closed without merge / test failure / reason
- [~] [clawband] PR pending — PR #42 jamessoubry/clawband
- [-] [shortlink] Parked item — not ready to implement yet
```

`[ ]` = pending · `[x]` = done · `[!]` = failed · `[~]` = PR open, awaiting merge · `[-]` = parked (skip forever until changed to `[ ]`)

`[~]` items are not re-implemented — on the next run `/backlog` checks if the PR merged and either deploys or reminds you.

`[-]` items are **permanently skipped** — the skill never processes them. Change to `[ ]` manually when ready to implement.

## GitHub issues mode — issue conventions

- Issues must have the `backlog` label to be queued
- Priority ordering: `P0` → `bug` → `P1` → `P2` → unlabelled (bugs always jump the queue without needing a P-label; only use P-labels for genuine escalations)
- State is tracked via labels and issue open/closed state:
  - Queued: open + `backlog` label only
  - In progress: open + `in-progress` label (`backlog` removed when checked out)
  - PR pending: open + `pr-pending` label (`backlog` and `in-progress` both removed)
  - Done: closed
  - Failed: open + `failed` label (stays open for manual retry/fix)
- The project is inferred from the repo name (e.g. `jamessoubry/clawband` → `clawband`)

## Project config — `.backlog.yml`

Each project can define a `.backlog.yml` in its root directory. The skill reads this first; the project map below is a fallback for projects that don't have one.

```yaml
# <project_dir>/.backlog.yml
repo: jamessoubry/clawband      # GitHub repo (optional — skip GitHub steps if absent)
deploy: cargo build --release   # deploy command (overrides fallback map)
label: backlog                  # issue label to filter on (default: backlog)
priority: [P0, P1, P2]         # priority label order, high→low (default)
pr_required: false              # if true: push branch + open PR instead of pushing to main; poll for merge before deploying
pr_poll_interval: 300           # seconds between merge checks (default: 300)
pr_timeout: 86400               # seconds before giving up on a PR (default: 86400 = 24h)
notify: bash ~/main/scripts/notify-main.sh "{message}"  # notification command; {message} is substituted. Omit to skip notifications.
```

When reading project config, check `<project_dir>/.backlog.yml` first. If it exists, use those values. If it doesn't exist or a field is missing, fall back to the project map below.

## Project map (fallback)

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

### Step 0 — Lockfile check

Before any work, check for a global lockfile that prevents two backlog runs competing for RAM:

```bash
LOCK=/tmp/backlog.lock
if [ -f "$LOCK" ]; then
  OWNER=$(cat "$LOCK")
  # Notify using NOTIFY_CMD if available, else skip
  echo "Backlog already running: $OWNER — try again when it finishes"
  STOP
fi
echo "<project> — started $(date -u +%H:%M:%SZ)" > "$LOCK"
```

Release the lockfile at the end of every outcome path (success, failure, PR pending, or early stop):
```bash
rm -f "$LOCK"
```

### Step 1 — Find the next item

**File mode:**
Read the file. Check for `[~]` lines first (PR pending), then `[ ]` lines.

If a `[~]` line exists:
```bash
# Extract PR number and repo from the line, e.g. "PR #42 jamessoubry/clawband"
unset GITHUB_TOKEN
STATE=$(gh pr view <PR_NUMBER> --repo <REPO> --json state --jq '.state')
```
- If `MERGED`: proceed to deploy (skip implement/test — jump straight to release/deploy step), then mark `[~]` → `[x]`
- If `OPEN`: `bash ~/main/scripts/notify-main.sh "Backlog [project]: PR #N still open — merge it then re-run /backlog"` then STOP
- If `CLOSED`: mark `[~]` → `[!] — PR closed without merge` then continue to next item

If no `[~]` exists, find the **first** `[ ]` line. **Skip any `[-]` lines entirely — they are parked and must not be processed.**
If neither exists (only `[x]`, `[!]`, `[-]` lines remain): `bash ~/main/scripts/notify-main.sh "Backlog complete: all items in <filepath> processed"` then STOP — do NOT call ScheduleWakeup.

**GitHub issues mode:**

Load `.backlog.yml` from the project dir (inferred from repo name) to get `BACKLOG_LABEL` and `PRIORITY_LABELS`.

**First: check for any pr-pending issue** (these no longer carry the `backlog` label, so need a separate query):

```bash
unset GITHUB_TOKEN
PR_PENDING=$(gh issue list --repo "<owner/repo>" \
  --label "pr-pending" --state open --limit 1 \
  --json number,title --jq '.[0]')
```

If a pr-pending issue is found:
- Extract `ISSUE_NUMBER` from it
- Find the associated PR: `gh pr list --repo "<owner/repo>" --state all --limit 50 --json number,body,state --jq --arg n "#$ISSUE_NUMBER" '[.[] | select(.body | contains($n))] | .[0]'`
- Check PR state and handle (MERGED → deploy + close; OPEN → notify + stop; CLOSED → remove `pr-pending` label + continue to queue)

If no pr-pending issue: find the **next queued item**:

```bash
unset GITHUB_TOKEN
# BACKLOG_LABEL from .backlog.yml or default "backlog"
# PRIORITY_LABELS from .backlog.yml or default ["P0","P1","P2"]
ISSUE_JSON=$(gh issue list --repo "<owner/repo>" \
  --label "$BACKLOG_LABEL" --state open --limit 100 \
  --json number,title,labels \
  --jq --arg p0 "${PRIORITY_LABELS[0]}" --arg p1 "${PRIORITY_LABELS[1]}" --arg p2 "${PRIORITY_LABELS[2]}" '
    def priority:
      .labels | map(.name) |
      if contains([$p0]) then 0
      elif contains(["bug"]) then 1
      elif contains([$p1]) then 2
      elif contains([$p2]) then 3
      else 4 end;
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

### Step 4 — GitHub issue: set in-progress label

**File mode:** look up `REPO` from the project map. If `—`, skip. Otherwise find or create an issue as before (search by feature title, create if not found). Then add `in-progress` label.

**GitHub issues mode:** `REPO` and `ISSUE_NUMBER` already known from Step 1. Add `in-progress` and remove `backlog` together:
```bash
unset GITHUB_TOKEN
gh issue edit "$ISSUE_NUMBER" --repo "$REPO" --add-label "in-progress" --remove-label "backlog"
```

Pass `ISSUE_NUMBER` and `REPO` into the workflow for coder and releaser.

### Step 5 — Load project config and context

First, read project config. Check for `<project_dir>/.backlog.yml`:
```bash
python3 -c "
import yaml, sys
try:
    cfg = yaml.safe_load(open('<project_dir>/.backlog.yml'))
    print(yaml.dump(cfg))
except: print('NOT_FOUND')
"
```
Use values from the YAML if present; fall back to the project map for any missing fields.
Key values to resolve: `REPO`, `DEPLOY_CMD`, `BACKLOG_LABEL` (default: `backlog`), `PRIORITY_LABELS` (default: `[P0, P1, P2]`).

Then read `<project_dir>/CLAUDE.md` to understand architecture, build commands, test commands, and deploy pipeline before dispatching agents.

### Step 6 — Run the feature pipeline

Use the Workflow tool with three phases:

**Phase 1 — Implement** (label: `coder`)
- Agent reads the project codebase and implements the feature
- Makes targeted changes — no scope creep
- Writes or updates tests alongside the feature
- Commits with a clear message but does NOT push yet
- If `ISSUE_NUMBER` is set, append `Closes <REPO>#<ISSUE_NUMBER>` as a footer line in the commit message

**Phase 2 — Test** (label: `tester`)
- Agent runs the project's test suite
- Verifies new tests pass and no regressions introduced
- If tests fail: return failure details, abort pipeline

**Phase 3 — Release** (label: `releaser`)

Only runs if Test phase passed. Behaviour depends on `pr_required` from `.backlog.yml`:

**`pr_required: false` (default):**
- `unset GITHUB_TOKEN && git push` direct to main
- Run deploy command
- Returns "SUCCESS: deployed" or "FAILURE: <reason>"

**`pr_required: true`:**
- Push to a feature branch: `git checkout -b backlog/<slug> && git push -u origin backlog/<slug>`
- Open a PR: `unset GITHUB_TOKEN && gh pr create --repo "$REPO" --title "<feature>" --body "Closes #$ISSUE_NUMBER\n\nAutomated via /backlog" --base main`
- Return "PR_PENDING: <pr_number>" — do NOT deploy yet, no background agent, no polling

### Step 7 — Update state

On **SUCCESS** (pr_required false, all phases passed):
```bash
# File mode: mark done
- [ ] [project] feature  →  - [x] [project] feature

# GitHub (both modes)
unset GITHUB_TOKEN
gh issue close "$ISSUE_NUMBER" --repo "$REPO" --comment "✓ Released" 2>/dev/null || true
gh issue edit "$ISSUE_NUMBER" --repo "$REPO" \
  --remove-label "in-progress" --remove-label "backlog" 2>/dev/null || true
```

On **PR_PENDING** (pr_required true, PR opened successfully):
```bash
# File mode: mark as [~] with PR reference
- [ ] [project] feature  →  - [~] [project] feature — PR #<pr_number> <REPO>

# GitHub issues mode: swap in-progress for pr-pending (backlog already removed in Step 4)
unset GITHUB_TOKEN
gh issue edit "$ISSUE_NUMBER" --repo "$REPO" --add-label "pr-pending" --remove-label "in-progress"
```

Zero polling. Zero ongoing cost. The next `/backlog` run detects `pr-pending` issues via a dedicated query (Step 1), checks the PR in one API call, and deploys if merged.

On **FAILURE** (any phase failed):
```bash
# File mode: mark failed
- [ ] [project] feature  →  - [!] [project] feature — <one-line reason>

# GitHub (both modes) — backlog already removed in Step 4; just swap in-progress for failed
unset GITHUB_TOKEN
gh issue comment "$ISSUE_NUMBER" --repo "$REPO" --body "✗ Failed: <reason>"
gh issue edit "$ISSUE_NUMBER" --repo "$REPO" \
  --add-label "failed" --remove-label "in-progress" 2>/dev/null || true
```

### Step 8 — Notify and release lock

Release the lockfile, then notify:

```bash
rm -f /tmp/backlog.lock
```

Read `NOTIFY_CMD` from `.backlog.yml`. If absent, skip notification.

Otherwise substitute `{message}` in `NOTIFY_CMD` with the notification text and run it:

```bash
# On success:
MSG="Backlog [project]: <feature> — ✓ released"
# On failure:
MSG="Backlog [project]: <feature> — ✗ failed: <reason>"

# Substitute and run:
CMD="${NOTIFY_CMD//\{message\}/$MSG}"
eval "$CMD"
```

Also release the lock on early-stop paths (backlog complete, PR still open):
```bash
rm -f /tmp/backlog.lock
```

## Rate limit recovery

ScheduleWakeup is called at the very start (Step 2), before any work begins. If the session is killed mid-tick, the wakeup fires and retries. The pipeline is idempotent:
- File mode: item still `[ ]` → retry; `[x]`/`[!]` → skip
- GitHub issues mode: issue still open with `backlog` label → retry; `pr-pending` issues are caught by the dedicated first query in Step 1 and checked immediately; closed or `failed` issues are absent from both queries and skipped naturally

## Constraints

- One item per tick — never process multiple items in one invocation
- Never deploy without passing tests — mark `[!]`/`failed` and move on if tests fail
- Always notify on every outcome (success or failure)
- One commit per feature item, never squash
