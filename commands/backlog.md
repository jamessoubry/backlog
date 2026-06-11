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

### Step 1 — Find the next item

**File mode:**
Read the file. Find the **first** line matching `- [ ]`.
If none exist: `bash ~/main/scripts/notify-main.sh "Backlog complete: all items in <filepath> processed"` then STOP — do NOT call ScheduleWakeup.

**GitHub issues mode:**

Load `.backlog.yml` from the project dir (inferred from repo name) to get `BACKLOG_LABEL` and `PRIORITY_LABELS`. Then:

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
      elif contains([$p1]) then 1
      elif contains([$p2]) then 2
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
- Before running tests: `python3 ~/backlog/trello.py card-move "$CARD_ID" test`
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
- Return "PR_PENDING: <pr_number>" — do NOT deploy yet
- The deploy happens after the PR is merged (see Step 7b)

### Step 7 — Update state, Trello, and GitHub

On **SUCCESS** (pr_required false, all phases passed):
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

On **PR_PENDING** (pr_required true, PR opened successfully):
```bash
# File mode: leave as [ ] — not done until merged and deployed
# Trello: move to a "review" list if available, else leave in_progress
python3 ~/backlog/trello.py card-comment "$CARD_ID" "PR #<pr_number> opened — awaiting merge"

# GitHub: PR is open, issue stays in-progress
# Notify
bash ~/main/scripts/notify-main.sh "Backlog [project]: <feature> — PR #<pr_number> opened, awaiting merge"
```

Then spawn a **background merge-watcher agent** with all context it needs to finish the job:

```
Agent(
  description: "Wait for PR <REPO>#<PR_NUMBER> to merge, then deploy",
  run_in_background: true,
  prompt: """
    You are a merge-watcher. Wait for PR #<PR_NUMBER> in <REPO> to be resolved, then
    complete the backlog release.

    Context:
      project_dir: <PROJECT_DIR>
      deploy_cmd:  <DEPLOY_CMD>
      repo:        <REPO>
      pr_number:   <PR_NUMBER>
      issue:       <ISSUE_NUMBER>   (empty if no GitHub issue)
      trello_card: <CARD_ID>
      feature:     <FEATURE>
      file:        <FILE_PATH>      (empty if GitHub issues mode)
      timeout_sec: <PR_TIMEOUT>     (from .backlog.yml, default 86400)
      poll_sec:    <PR_POLL_INTERVAL> (from .backlog.yml, default 300)

    Steps:
    1. Use the Monitor tool to watch:
         bash -c 'until unset GITHUB_TOKEN && gh pr view <PR_NUMBER> --repo <REPO> --json state --jq ".state != \"OPEN\"" | grep -q true; do sleep <poll_sec>; done && echo done'
       Monitor fires when the PR leaves OPEN state (merged or closed).

    2. Check the final state:
         unset GITHUB_TOKEN && gh pr view <PR_NUMBER> --repo <REPO> --json state --jq '.state'

    3a. If MERGED:
        - cd <project_dir> && <deploy_cmd>
        - python3 ~/backlog/trello.py card-move <CARD_ID> done
        - python3 ~/backlog/trello.py card-comment <CARD_ID> "✓ Released"
        - If issue set: unset GITHUB_TOKEN && gh issue close <ISSUE_NUMBER> --repo <REPO> --comment "✓ Released"
        - If file set: update [ ] → [x] for the feature line
        - bash ~/main/scripts/notify-main.sh "Backlog [<project>]: <feature> — ✓ released"

    3b. If CLOSED without merge OR Monitor timed out (>timeout_sec elapsed):
        - python3 ~/backlog/trello.py card-move <CARD_ID> blocked
        - python3 ~/backlog/trello.py card-comment <CARD_ID> "✗ PR closed without merge"
        - If issue set: unset GITHUB_TOKEN && gh issue edit <ISSUE_NUMBER> --repo <REPO> --add-label failed --remove-label in-progress
        - If file set: update [ ] → [!] <feature> — PR closed without merge
        - bash ~/main/scripts/notify-main.sh "Backlog [<project>]: <feature> — ✗ PR closed without merge"
  """
)
```

The background agent handles completion entirely — the main backlog tick ends here for `pr_required` items. The item stays `[ ]` / `in-progress` until the watcher finishes.

On **FAILURE** (any phase failed):
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
