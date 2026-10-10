---
id: A-000
project: project-slug
title: "CEO review: <reason: batch closed / stalled N days>"
owner: ceo
type: review
status: todo
priority: high
due:
created: YYYY-MM-DD
closed:
size: small
autonomy: full
source: local
profile:
blocked_by: []
unblocked_by:
decision:
evidence:
lock:
---

# CEO review: <reason>

## Goal

Review the project in the ceo role's "Review" mode: verify evidence of closed tasks, count stalls, update `LOG.md`, add the next batch up to `wip_limit`.

## Steps

- [ ] Open the evidence of every task closed since the last review. Missing evidence: back to `todo` with a note.
- [ ] Stalls: `in_progress` without a live lock and unchanged for 48 h; tasks 3+ days overdue without progress; instructions in `LOG.md` from the last 14 days without a task file. Each gets a decision now.
- [ ] Human tasks moved twice: new channel, delegate, or proposed cancellation (no third postponement).
- [ ] WIP balance: how many open tasks serve the first unmet success criterion? Under half: reason in `LOG.md` or cut.
- [ ] Last mile: which task in the next batch performs the action in a success criterion (send, publish, sell)? None: say why in `LOG.md`.
- [ ] A criterion due within 14 days with no task: create a decision (reword, move, drop) with a recommendation.
- [ ] Is the goal still right? If not, edit `PROJECT.md` first.
- [ ] Add the next batch up to `wip_limit`.
- [ ] Regenerate the dashboard.

## Definition of done

`LOG.md` has a dated review entry with the counts above; new tasks exist (or the log says why not); the dashboard is regenerated. Evidence: paths of the changed files.

## Owner notes

## Progress log
