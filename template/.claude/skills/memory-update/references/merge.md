# Merging signals into now.md

now.md is the dynamic working context: what is happening now, what matters this week, what was decided. It is not a history; old lines leave.

## Inputs

1. The current `.claude/rules/now.md` (may not exist yet).
2. The signal list from extraction.
3. `{{engine}} status` output (or task frontmatter) for every task ID involved.

## Adding (type NEW)

| Signal | Section |
|---|---|
| Project | "Active projects" table |
| Decision | "Recent decisions", with date |
| Priority | "Priorities" (max 5) |
| Blocker | "Blockers" |
| Stack | a note on the project row, or a dated line in "Recent decisions" |

## Updating (type UPDATE)

Find the existing line and change it. Never add a second row for the same project.

## Removing (FINISHED / REMOVE and staleness)

| Item | Rule |
|---|---|
| Finished project | remove 7 days after it finished |
| Decision marked `[x]` | remove after 14 days |
| Resolved blocker | remove immediately |
| Last week's priority | remove unless it came up again |
| Confirmed pattern | keep until it changes |

## Conflicts

- Newer facts replace older ones (add the date).
- A newer decision replaces an older one.
- Priorities are replaced, not accumulated (max 5).
- When a session statement and a task file disagree about a status or due date, **the file wins**.

## Task statuses come from files (hard rule)

Before writing or keeping any line that names an `A-`/`H-` ID (in "Open decisions", "Priorities", "Blockers", "Active projects"), check its status and due date in the engine output or the file frontmatter. A task that is `done` or `cancelled` never appears as open: remove it, or write `- [x] ~~...~~ (closed YYYY-MM-DD: <outcome>)`. "N days overdue" is computed from `due:`, not remembered.

Why: a context file written from conversation drifts within days. Decisions already closed keep showing as "waiting on the owner", and the owner keeps getting asked about things that are settled.

## Priority order (hard rule)

Order "Priorities" by what is actually late, not by what was discussed last:
1. Overdue human tasks and decisions (oldest due first) from the engine status.
2. Items due today.
3. Then the session's own priorities.

Never reorder engine-reported overdue items below fresh conversation topics. Recency is not importance.

## now.md format

```markdown
# NOW — current context

*Last update: YYYY-MM-DD HH:MM*

## Active projects
| Project | Status | Due | Notes |
|---|---|---|---|

## Priorities
1. ...

## Open decisions
- [ ] ...

## Recent decisions
- YYYY-MM-DD: ...

## Blockers
- ...
```

## Limits

- **Max 120 lines.** Near the limit, drop the oldest lines first.
- Do not duplicate persona.md, soul.md, context.md.
- Update the "Last update" timestamp to now.
- Keep every heading even when empty; write `- (none)`.

## Output

The full updated now.md, ready to save.
