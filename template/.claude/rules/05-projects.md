# 05 · The project system

How goals become tasks and tasks become results. The engine (`{{engine}} guard`) enforces some of these automatically; the rest are on you.

---

## 29. A project is a goal, a measurable success criterion with a date, and what is out of scope

**Rule.** `PROJECT.md` has a goal, success criteria that are measurable and dated ("10 paying customers by 2026-12-31", not "grow sales"), constraints, and an `## Out of scope` section. Expanding scope without a measurable criterion requires a decision task, in the same session, with the proposed wording of the criterion.

**Why.** In one week about 70% of a project's 46 tasks served a scope expansion that had no criterion in `PROJECT.md`. Nobody could tell when that work would be finished, so it never was.

**How to apply.** If the human gives a threshold without a time frame ("ROI 15%"), ask "over what period?" in the same conversation, before writing it down. When a criterion's date passes, update it to the actual state with one line in `LOG.md`.

## 30. One owner per task

**Rule.** `owner:` holds exactly one role or `human`. Never two, never "we", never "team".

**Why.** Shared ownership leaves nobody to ask when work stalls. The queue, the guard and every review need one name to route the task to.

**How to apply.** If two roles are needed, it is two tasks with `blocked_by`.

## 31. WIP limit

**Rule.** Active agent tasks per project (`A-` in `todo`, `in_progress`, `blocked`) stay at or under `wip_limit` (default 5). Further work waits in `PLAN.md` as phases. Human tasks do not count. Raising the limit needs an end date and a reason in `LOG.md`.

**Why.** Three projects quietly raised their limits to between 8 and 28 with no end date. Queues filled up, reviews stopped cutting, and the owner faced a wall of half-finished work.

**How to apply.** The dashboard flags projects over the limit. A review in an over-limit project starts by cutting, not by adding.

## 32. "Waiting for the human" without a task is an illegal state

**Rule.** A task with `status: blocked` has `unblocked_by: H-NNN` and a `## Unblocking action` section. If it does not, the guard creates the human task.

**Why.** Seven commitments from the owner (a screencast for an app review, a go-ahead for a sales channel, a registration form) lived only in a notes file. Nobody had forgotten them, but none was a task, so the work behind them stood for weeks.

**How to apply.** When you block, create the `H-` task first, then set `blocked` and point to it.

## 33. A human task takes 15 minutes or less and starts with a 1 to 3 minute step

**Rule.** Every `H-` task fits in 15 minutes and opens with a concrete first step that takes 1 to 3 minutes: "open file X", "log in to Y", "call Z at this number". Everything the human needs (paths, links, drafts) is in the task. Longer work is split or given to a role.

**Why.** The owner is the bottleneck of every project, and big vague tasks ("sort out the insurance") sat for weeks while small ones moved. A first step that takes two minutes is what gets a busy person started; it is not decoration.

**How to apply.** The agent prepares everything up to the last click: the draft in the outbox, the form pre-filled, the number to call. The human executes.

## 34. A decision is a separate task, with a recommendation

**Rule.** A choice only the human can make is a `type: decision` task with exactly one question. `## For approval` holds a ready recommendation (yes/no, or option A over B), its cost (money, time, risk) and what happens after acceptance. Never an open question ("what do you think?"), never an item on a numbered list.

**Why.** A decision about kitchen fittings in a building was item 4 of a list of questions. The owner answered the easy ones; that one was never answered and surfaced months later. Two other decisions asked as open questions came back as "you propose" and stalled.

**How to apply.** Before creating a decision, apply rule 4 (look it up) and rule 8 (zero-cost pattern). If it is still a decision, the human should be able to decide in 30 seconds without opening another file.

## 35. An accepted decision without an executing task is an illegal state

**Rule.** Accepting a decision does nothing by itself. Every accepted decision gets an executing `A-` task (due two days after acceptance, quoting `## For approval`). Tasks blocked by that decision are unblocked. The guard enforces both.

**Why.** Three times in a few weeks the owner accepted a decision and nothing happened: a test portfolio sat unfunded for four days, a business context file stayed wrong for a day, a technical block lasted most of a day. Each time the click felt like progress.

**How to apply.** Before executing, read both `decision:` and the latest `## Owner notes`: an approval often comes with a condition ("yes, but the cheaper option").

## 36. Embargo is a date, not a sentence

**Rule.** A task that must wait for a date (end of a notice period, a contract date, a launch day) never carries "do not start before X" as a step in its text. Keep it in `PLAN.md` with the date and let the review create it on time, or block it on a dated human task.

**Why.** A task had "do not execute before the 31st" as its first step. The date passed and the task sat silent for two more days, because nothing read the sentence.

**How to apply.** Dates that machines must act on go into fields or into the plan the CEO reviews, never only into prose.

## 37. The last mile has a task; reviews count stalls

**Rule.** Each batch contains at least one task that performs the action in a success criterion (sell, send, publish, launch). Each review counts stalled work, not only closed work: `in_progress` without movement for 48 hours, tasks 3+ days overdue, instructions without files. A human task moved twice gets a new channel, a delegate, or a proposed cancellation; there is no third postponement.

**Why.** An audit found four of six projects had carried the work right up to the action in their success criterion and stopped there: a purchase path mapped but no test purchase ordered; twelve documents written and zero posts published. The reviews counted closed tasks and looked healthy.

**How to apply.** Use `projects/.templates/task-review.md`; its checklist covers these counts.

## 38. Analysis does not replace contacting the other side

**Rule.** A criterion that depends on a customer, supplier or authority gets tasks that prepare the contact completely, and the contact itself as a human task whose first step is "send" or "call". Another version of the same measurement needs a written reason why it could change the verdict.

**Why.** The planner was good at ordering what can be calculated and bad at ordering what needs another person. One project had seven measurements of the same ceiling while the one phone call that mattered stayed undone. Another had a print-ready book and zero quotes from printers.

**How to apply.** In a review, ask of each criterion: is the bottleneck a number or a person? If a person, the next task is a draft and a send.

## 39. Dashboards are generated, never hand-written

**Rule.** `projects/dashboard.md` and the block between `<!-- AGENTOS:START -->` and `<!-- AGENTOS:END -->` in `TODO.md` are written only by `{{engine}} dashboard`.

**Why.** Task files are the single source of truth. A hand-edited status page is a second copy, and two copies maintained by hand always diverge; the human then trusts the wrong one.

**How to apply.** If the dashboard is wrong, fix the task file and regenerate. Write freely outside the markers in `TODO.md`.

## 40. Do not cancel the human's tasks for them

**Rule.** Agents may close an `H-` task as `done` when the work was demonstrably completed another way and the evidence is in a file. Cancelling, merging or rescoping `H-` tasks is the human's call; agents propose it in a report.

**Why.** A planner cancelled one of the owner's tasks and merged two others during a review. The owner had context the planner lacked, and had to undo it.

**How to apply.** Write the proposal in the review report and in the task's `## Progress log`. Leave `status` alone.
