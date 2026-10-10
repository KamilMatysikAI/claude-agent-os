---
name: project
description: Runs agent-led projects — status of all projects, status of one, a ceo review that checks evidence and adds the next batch of tasks, or executing a project's open agent tasks through their roles. Use for "/project", "how are the projects", "project status", "what is blocked", "move <project> forward", "review the project", "next batch", "run the tasks of <project>".
argument-hint: "[empty = all] | <slug> | <slug> review | <slug> run"
allowed-tools: ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Agent", "Skill"]
---

# /project — run projects

Projects live in `projects/<slug>/` (PROJECT.md, PLAN.md, LOG.md, tasks/, materials/). Roles live in `.claude/agents/`. Computation (dashboard, guard, status, picking the next task) belongs to the engine CLI. This skill decides **what happens now**.

## Modes

| Mode | Call | What you do |
|---|---|---|
| `status` (default) | `/project` | Regenerate views, report all projects. Execute nothing. |
| `<slug>` | `/project shop-relaunch` | One project: phase, open tasks, blockers, what waits on the owner. |
| `<slug> review` | `/project shop-relaunch review` | ceo review: verify closures, update phase and LOG, add the next batch. |
| `<slug> run` | `/project shop-relaunch run` | Execute open agent tasks of this project through their roles. |

## Status

```
{{engine}} guard
{{engine}} dashboard
{{engine}} status [<slug>]
```

Then read `projects/dashboard.md` (and `projects/<slug>/PLAN.md` + the last entries of `LOG.md` for a single project) and report briefly. **At the top, always: what waits on the owner (H- tasks, decisions) and what is blocked.** Everything else below.

Flag the stall signals the dashboard shows: done without evidence, blocked tasks, tasks in progress with no log line for days, due dates passed. If the CLI is not available, say so; do not hand-write the dashboard.

## Review (ceo)

Call the `ceo` agent (`subagent_type: "ceo"`; if unavailable, follow `.claude/agents/ceo.md` yourself) with:

> Review project `<slug>`. 1) For every task closed since the last review, check `evidence:` actually exists (open the file, follow the link). Missing or fake evidence → reopen with a log line. 2) Read the latest `## Owner notes` in open tasks; they override the plan. 3) Count stalls, not only closures: tasks with no progress for N days, blocked tasks, due dates moved more than twice. 4) Update the phase in `PLAN.md` and add one dated entry to `LOG.md`. 5) Add the next batch, staying within `wip_limit` active agent tasks (todo + in_progress + blocked). Over the limit → close or cancel before adding. 6) Every human dependency becomes an `H-` task (15 min or less, first step 1–3 min); every owner choice becomes a `type: decision` task with a recommendation in `## For approval`. 7) If the success criterion's date has passed, propose an update as a decision task. Never cancel, merge or rescope a human task yourself; propose it in the log.

After the review: `{{engine}} guard`, `{{engine}} dashboard`, then report the **difference**: what was added, what closed, what is still blocked and on whom.

## Run

1. See what the engine would pick: `{{engine}} run --dry-run`. Use that order. If the CLI is unavailable, use the order in the `agent-queue` skill.
2. For each open agent task in this project (`owner` is a role, `status` todo or in_progress, no live `lock`, nothing open in `blocked_by`, `autonomy: full`):
   - Run it with the `agent-queue` skill on that file. It handles locks, progress lines, evidence and blocking.
   - `autonomy: ask` tasks: show the plan and wait for the owner's OK in this session.
3. **Fail-safe per task.** One failed task never stops the rest. A failure stays `in_progress` with a log line saying what went wrong and what is next.
4. Stop when the session's context is getting long; write progress first. The queue is resumable.
5. At the end: `{{engine}} guard`, `{{engine}} dashboard`, short report.

## Guard rules (enforced by the engine, explained here)

`{{engine}} guard` is idempotent and safe to run any time. It:
- turns `status: blocked` without `unblocked_by` into a human mini-task and links it;
- turns an accepted decision with no executing agent task into one (due = accept date + 2 days, scope quoted from `## For approval`);
- flags `done` without `evidence` in the dashboard.

You do not reimplement these. You make sure the files are in a state the guard can read: correct frontmatter keys, `unblocked_by` filled when you block, `blocked_by` pointing at the decision ID when a task waits on a decision.

## Rules

Numbered in `.claude/rules/05-projects.md` (29–40).

- "Waiting on the owner" without an `H-` task is not allowed.
- An accepted decision without an executing task is not allowed.
- WIP limit from `PROJECT.md` (`wip_limit`, default from `agentos.toml`). Over the limit, the ceo finishes work instead of adding.
- A task that must wait for a date carries it in `PLAN.md` or a dated human task, never as a sentence in its steps (rule 36).
- Closing requires evidence. A rejected decision needs no follow-up task; doing nothing is the correct result.
- Ad-hoc tasks outside projects (`inbox/`) belong to the `agent-queue` skill. Do not mix them into project batches.
