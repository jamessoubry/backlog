# backlog

A Claude Code skill that works through a backlog one feature at a time — from a markdown file or GitHub issues. Each tick: pick the next item, implement it with coder/tester/releaser subagents, mark it done, and self-pace to the next tick. Survives rate limit resets automatically.

## Install

```bash
cp commands/backlog.md ~/.claude/commands/backlog.md
```

## Usage

Two modes:

### File mode

```bash
/backlog ~/myproject/backlog.md
```

Backlog file format:

```markdown
- [ ] [myproject] Add rate limiting to the API
- [ ] [myproject] Fix timeout in the background worker
- [x] [myproject] Already done — skipped
- [!] [myproject] Failed item — reason noted inline
- [~] [myproject] PR open — PR #42 owner/repo
```

| Status | Meaning |
|--------|---------|
| `- [ ]` | Pending |
| `- [x]` | Done |
| `- [!]` | Failed — skipped, reason appended inline |
| `- [~]` | PR open — checked on next run, deployed if merged |

### GitHub issues mode

```bash
/backlog owner/repo
```

Issues must have the `backlog` label. Priority ordering: `P0` → `bug` → `P1` → `P2` → unlabelled. Bugs always jump the queue without needing a P-label.

State tracked via labels:
- Queued: `backlog`
- In progress: `in-progress` (`backlog` removed on checkout)
- PR pending: `pr-pending`
- Done: closed
- Failed: `failed` (stays open for manual retry)

### No-argument mode

```bash
/backlog
```

Reads `.backlog.yml` from the current directory. If it has a `repo:` field, uses GitHub issues mode for that repo.

## Per-project config

Create `.backlog.yml` in a project root:

```yaml
repo: owner/repo           # GitHub repo (required for GitHub steps)
deploy: ./deploy.sh        # deploy command
label: backlog             # issue label to filter on (default: backlog)
priority: [P0, P1, P2]    # priority label order, high→low
pr_required: false         # if true: push branch + open PR instead of pushing to main
```

When `pr_required: true`, the releaser pushes a feature branch and opens a PR instead of deploying directly. The item is marked `[~]` / `pr-pending`. On the next `/backlog` run, the PR is checked: merged → deploy; still open → notify and stop; closed without merge → mark failed.

## How it works

Each tick:
1. Schedules a recovery wakeup before any work begins
2. Picks the next item (checks PR-pending items first)
3. Runs a three-phase Workflow: **Implement → Test → Release**
4. Updates state and notifies via Telegram

270s between ticks — within the 5-minute prompt cache TTL, giving the rolling window room to recover. If a session is killed mid-tick, the queued wakeup retries the item.
