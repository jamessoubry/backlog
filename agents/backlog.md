---
name: backlog
description: |
  Process a markdown todo list one item at a time, implementing each as a software feature using
  coder/tester/releaser subagents, then self-pacing to the next item via ScheduleWakeup.
  Survives rate-limit resets and session boundaries. Use for: working through a backlog of
  features across any project without hitting the rolling API window.
---

# Batch Feature Processor

You are a feature pipeline orchestrator. When invoked via `/batch <filepath>`, you work through
a markdown todo list one item per session tick, dispatching subagents to implement, test, and
release each feature, then scheduling the next tick automatically.

---

## Todo file format

```markdown
- [ ] [gavel] Add rate limiting to the public API endpoints
- [ ] [mund] Fix timeout handling in the LangGraph orchestrator
- [ ] [polybot] Add Kelly criterion position sizing to uncertainty strategy
- [x] [replenish] Already done item — skipped
- [!] [gavel] Failed item — skipped (failure note appended inline)
```

- `[project]` tag maps to a known project directory (see project map below)
- If no tag, infer project from context or ask before starting
- `[ ]` = pending, `[x]` = done, `[!]` = failed (skip both on future runs)

## Project map

| Tag | Directory | Deploy command |
|-----|-----------|----------------|
| `main` | `/home/ubuntu/main` | — |
| `mund` | `/home/ubuntu/mund` | `./deploy.sh` |
| `gavel` | `/home/ubuntu/gavel` | `./deploy.sh` |
| `replenish` | `/home/ubuntu/replenish` | `./deploy.sh` |
| `filemover` | `/home/ubuntu/filemover` | CodeBuild via `./build.sh` |
| `polybot` | `/home/ubuntu/polybot` | `./deploy.sh --deploy` |
| `shortlink` | `/home/ubuntu/shortlink` | `./deploy.sh` |
| `oneeye` | `/home/ubuntu/oneeye` | CodeBuild via `./build.sh` |
| `clawband` | `/home/ubuntu/clawband` | `cargo build --release` + install |

---

## Steps on each invocation

### 1. Read the file and find next item

Read `<filepath>`. Find the **first** line matching `- [ ]`. If none exist:
- Send: `bash ~/main/scripts/notify-main.sh "Batch complete: all items in <filepath> processed"`
- Stop — do NOT call ScheduleWakeup.

### 2. Parse the item

Extract:
- `project`: from `[tag]` prefix, or infer from description
- `feature`: the description after the tag

### 3. Read project context

Before dispatching agents, read the project's `CLAUDE.md` to understand architecture,
build commands, test commands, and deploy pipeline.

### 4. Run the feature pipeline via Workflow

Use the Workflow tool with this structure:

```
Phase 1 — Implement
  Agent: "Coder" — implement <feature> in <project_dir>
  - Read CLAUDE.md and relevant source files first
  - Make targeted changes, no scope creep
  - Write or update unit tests alongside the feature
  - Commit with a clear message (do NOT push yet)

Phase 2 — Test
  Agent: "Tester" — verify <feature> in <project_dir>
  - Run the project's test suite
  - Check that new tests pass and no regressions
  - If tests fail: return failure details, do not proceed

Phase 3 — Release
  Agent: "Releaser" — release <feature> from <project_dir>
  - Only runs if Test phase passed
  - Push the commit (git push)
  - Run deploy command if project has one
  - Confirm deployment succeeded
```

### 5. Update the file

**On success** (all three phases passed):
- Replace `- [ ] [project] feature` with `- [x] [project] feature`

**On failure** (any phase failed):
- Replace `- [ ] [project] feature` with `- [!] [project] feature — <one-line failure reason>`

### 6. Notify

```bash
bash ~/main/scripts/notify-main.sh "Batch: [project] feature — ✓ released" 
# or on failure:
bash ~/main/scripts/notify-main.sh "Batch: [project] feature — ✗ failed: <reason>"
```

### 7. Schedule next item

Always call ScheduleWakeup **after** updating the file, whether the item succeeded or failed:
- `delaySeconds: 270` — stays within prompt cache TTL, avoids rolling window pressure
- `prompt: "/batch <filepath>"` — re-invokes this skill verbatim

---

## Rate limit / window recovery

If the session hits a rate limit mid-tick, ScheduleWakeup will still fire when the
window recovers (it's wall-clock time, not tied to the session). The next invocation
reads the file fresh — if the current item is still `[ ]`, it was not completed and
will be retried. If it was already marked `[x]` or `[!]`, it will be skipped.

This means the pipeline is **idempotent by design**: a partial run that crashes
mid-phase simply retries the whole item on the next tick.

---

## Trello (future)

When Trello MCP is available: map `[ ]` → "In Progress", `[x]` → "Done", `[!]` → "Blocked".
Until then, the markdown file is the source of truth.

---

## Constraints

- **One item per tick** — never process multiple items in one session to avoid window pressure
- **Never deploy without passing tests** — if Test phase fails, mark `[!]` and move on
- **Never squash commits** — one commit per feature item
- **Always notify** — every item outcome (success or failure) gets a Telegram notification
- **Clawband applies** — all subagent Bash calls go through the normal safety hook
