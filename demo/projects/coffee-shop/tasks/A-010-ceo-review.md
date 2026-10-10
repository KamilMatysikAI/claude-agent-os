---
id: A-010
project: coffee-shop
title: "CEO review: overdue blocker on the checkout path"
owner: ceo
type: review
status: todo
priority: high
due: 2026-10-11
created: 2026-10-10
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

# CEO review: overdue blocker on the checkout path

## Goal

Review the project in the ceo role's "Review" mode: verify evidence of closed tasks, count stalls, update `LOG.md`, add the next batch up to `wip_limit`.

## Context

H-005 is overdue and blocks A-006, which blocks criterion 1 (checkout live by 2026-10-31). H-013 is also overdue. The project is at its WIP limit (5 active agent tasks).

## Steps

- [ ] Open the evidence of every task closed since the last review. Missing evidence: back to `todo` with a note.
- [ ] Stalls: `in_progress` without a live lock and unchanged for 48 h; tasks 3+ days overdue without progress; instructions in `LOG.md` from the last 14 days without a task file. Each gets a decision now.
- [ ] Human tasks moved twice: new channel, delegate, or proposed cancellation.
- [ ] WIP balance: how many open tasks serve the first unmet success criterion?
- [ ] Last mile: which task performs the action in a success criterion? None: say why in `LOG.md`.
- [ ] Is the goal still right? If not, edit `PROJECT.md` first.
- [ ] Add the next batch up to `wip_limit`.
- [ ] Regenerate the dashboard.

## Definition of done

`LOG.md` has a dated review entry with the counts above; new tasks exist (or the log says why not); the dashboard is regenerated. Evidence: paths of the changed files.

## Owner notes

## Progress log

- 2026-10-10 08:00 — Created by ceo: overdue human task on the critical path.
