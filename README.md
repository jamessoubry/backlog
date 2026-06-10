# backlog

A Claude Code skill that works through a markdown todo list one feature at a time, implementing each with coder/tester/releaser subagents, self-pacing to avoid rate limits, and resuming automatically after rolling window resets.

## How it works

Each tick:
1. Schedules the next tick immediately (before any work) — ensures recovery from mid-tick rate limit kills
2. Picks the first `- [ ]` item from the todo file
3. Runs a Workflow: **Implement → Test → Release**
4. Marks the item `[x]` (success) or `[!]` (failure) in the file
5. Notifies via Telegram

270s between ticks — stays within the 5-minute prompt cache TTL and gives the rolling window room to recover.

## Install

```bash
cp commands/backlog.md ~/.claude/commands/backlog.md
cp agents/backlog.md ~/.claude/agents/backlog.md
```

## Usage

Create a todo file:

```markdown
- [ ] [myproject] Add rate limiting to the API
- [ ] [myproject] Fix timeout in the background worker
- [ ] [otherapp] Add password-protected links
```

Run it:

```
/backlog ~/myproject/todo.md
```

It will process items one at a time, notifying you on completion of each, and stopping when the list is empty.

## Todo format

| Status | Meaning |
|--------|---------|
| `- [ ]` | Pending — will be processed |
| `- [x]` | Done — skipped |
| `- [!]` | Failed — skipped, failure note appended inline |

Tag format: `- [ ] [project] description`

## Rate limit recovery

`ScheduleWakeup` is called at the top of every tick before work begins. If the session is killed mid-tick by an exhausted rolling window, the queued wakeup fires when the window recovers. Incomplete items (still `[ ]`) are retried; completed items are skipped. The pipeline is idempotent.

## Roadmap

- [ ] Trello integration — map `[ ]` → In Progress, `[x]` → Done, `[!]` → Blocked
- [ ] Per-item agent type selection (e.g. `[myproject:hotfix]` uses a faster pipeline)
- [ ] Parallel items (multiple independent features in one tick)
