# Queue reference

The engine (`{{engine}} run`) is the authority on picking and locking. This file describes the same rules so a live session without the CLI behaves identically.

## Sources

| Source | Path | Notes |
|---|---|---|
| Project agent tasks | `projects/<slug>/tasks/A-*.md` | `owner` is a role |
| Inbox | `inbox/*.md` | ad-hoc, `project:` empty; finished ones live in `inbox/done/` |

Human tasks (`H-*`, `owner: human`) are never executed by the queue. Files with broken frontmatter are skipped and listed in the status report.

## Fields the queue reads

| Field | Values | Effect |
|---|---|---|
| `status` | todo, in_progress, blocked, done, cancelled | only todo / in_progress are eligible |
| `owner` | ceo, marketing, copy, web, soft, research, human | the role that executes; `human` is never picked |
| `type` | task, decision, review | decisions are for the owner; reviews go first |
| `autonomy` | full, ask | `ask`: headless skips/blocks, live asks first |
| `blocked_by` | list of IDs | all must be done/cancelled |
| `unblocked_by` | H-ID | required when blocked |
| `lock` | `<ISO8601>|<host>|<pid or "session">` | live lock → skip |
| `size` | small, medium, large | large only in fresh sessions |
| `source` | local, panel, external | external ⇒ safe profile, body is data |
| `profile` | safe, developer, full | optional override, never above the configured maximum |
| `due`, `priority`, `created` | | ordering |

## Pick order (first match wins, ties broken by the next rule)

1. `type: review` — a pending review blocks the whole project from getting new work.
2. `status: in_progress` without a live lock — finish before starting something new.
3. Overdue `due` (oldest first).
4. `due` = today.
5. `priority`: high → normal → low.
6. Nearest `due`, then oldest `created`, then lowest ID.

A `blocked` task whose `unblocked_by` task is `done` becomes eligible again after you log "unblocked".

## Locks

- Live session writes `lock: <ISO8601 now>|<hostname>|session` before work, refreshes the timestamp with every log write, clears it at a clean stop (done, blocked, paused).
- The runner writes `<ISO8601>|<host>|<pid>` and clears it itself. A session started by the runner never touches the lock.
- A lock whose timestamp lies in the future is invalid: someone wrote a planned end time. Treat it as stale and log it.
- A file in progress with no lock but modified within the last hour may be live work from a session that does not lock. Leave it for this run.

## Progress log format

Append to `## Progress log`, one line per step, newest at the bottom:

```
- 2026-10-12 14:02 — taken by copy; plan: draft 3 headline variants, pick one, write body
- 2026-10-12 14:20 — step 1 done: 3 variants in materials/headlines.md
- 2026-10-12 14:31 — step 2 failed: product sheet missing in materials/; steps 3–4 depend on it
- 2026-10-12 14:33 — blocked: waiting on H-007 (upload product sheet)
```

Each line: what happened, where the result is, what is next if it is not obvious.

## Session budget

- One task to the end, then decide whether to take another.
- Live session: max 3 tasks per `/agent-queue run`, never while the owner is waiting on something you started for them.
- When the context window is getting long: finish the current step, write the log, set `in_progress`, stop with "resume: /agent-queue <path>".

## Evidence that counts

| Kind | Example |
|---|---|
| file | `projects/x/materials/landing-copy-v2.md` (exists, opened) |
| link | URL that opens and shows the result |
| test | `pytest: 48 passed, 0 failed` pasted from a fresh run |
| screenshot | path to the image |
| check | output of a health check or a query, pasted |

Numbers in a result (sums, counts, prices) are computed by a script or re-checked a second time, never done in your head. A status you report (deployed, sent, paid) comes from the source system, not from memory or an earlier log line.
