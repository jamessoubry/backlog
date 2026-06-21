# backlog

A Claude Code skill that works through a backlog one feature at a time — from a markdown file or GitHub issues. Each tick: pick the next item, implement it with coder/tester/releaser subagents, mark it done, and self-pace to the next tick. Survives rate limit resets automatically.

## Install

```bash
curl -sL https://raw.githubusercontent.com/jamessoubry/claude-backlog/main/commands/backlog.md \
  -o ~/.claude/commands/backlog.md
```

Or manually copy `commands/backlog.md` into `~/.claude/commands/`.

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
notify: bash ~/main/scripts/notify-main.sh "[backlog] [myproject] {message}"
                           # notification command; {message} is substituted. Omit to skip.
```

The `notify` field is a shell command run after every tick. `{message}` is replaced with the outcome text (e.g. `feature — ✓ released` or `feature — ✗ failed: reason`). Examples:

```yaml
# Custom script (simplest — put your notification logic there)
notify: bash ~/notify.sh "[myproject] {message}"

# Slack incoming webhook
notify: >
  curl -s -X POST -H 'Content-type: application/json'
  --data '{"text":"[myproject] {message}"}'
  https://hooks.slack.com/services/T.../B.../xxx

# Discord webhook
notify: >
  curl -s -X POST -H 'Content-type: application/json'
  --data '{"content":"[myproject] {message}"}'
  https://discord.com/api/webhooks/.../xxx
```

When `pr_required: true`, the releaser pushes a feature branch and opens a PR instead of deploying directly. The item is marked `[~]` / `pr-pending`. On the next `/backlog` run, the PR is checked: merged → deploy; still open → notify and stop; closed without merge → mark failed.

## How it works

Each tick:
1. Schedules a recovery wakeup before any work begins
2. Picks the next item (checks PR-pending items first)
3. Runs three sequential agents: **Implement → Test → Release**
4. Updates state and runs the `notify` command (if configured)

270s between ticks — within the 5-minute prompt cache TTL, giving the rolling window room to recover. If a session is killed mid-tick, the queued wakeup retries the item.

**Survives context compaction.** Before spawning any agents, the skill checks `git log` for a `[backlog]` commit from a prior run. If the coder already committed but the releaser never pushed, the next tick skips straight to release. Work is never duplicated.

## Customising agent behaviour via CLAUDE.md

Each agent reads the project's `CLAUDE.md` before doing anything. This is where you shape how the pipeline behaves for your specific project — build commands, commit conventions, cadence rules, and releaser overrides all belong here.

```markdown
# myproject

## Build & test

```bash
npm test              # run full test suite
npm run lint          # must pass before commit
```

## Commit conventions

- Branch: `feat/<slug>` for features, `fix/<slug>` for bugs
- Commit message: `feat:` / `fix:` prefix, e.g. `feat: add rate limiting`
- Always run `npm run lint` before committing

## Backlog pipeline — cadence

Run one feature at a time. Most items touch the same core files, so
concurrent open PRs will conflict. Wait for the current PR to merge
before running `/backlog` again.

## Backlog pipeline — releaser

When the releaser agent runs for this project:
- **Do NOT push directly to main** — push a feature branch and open a PR
- Do NOT run the deploy command — that runs automatically after merge via CI
- Mark the release step as SUCCESS once the PR is open and CI is green
- Check CI: `gh pr checks --watch --repo owner/myproject`
```

The agents pick up whatever is in `CLAUDE.md` — build steps, linting requirements, branch naming rules, PR conventions. You don't need to modify the skill itself; the CLAUDE.md is the extension point.
