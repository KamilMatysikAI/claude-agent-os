# CLAUDE.md

This workspace runs a small company of agents for {{owner_name}}. One planner (`ceo`) turns goals into tasks, five roles do the work, a queue runs tasks on a schedule, and {{owner_name}} gets only two kinds of work: short tasks (15 minutes or less) and decisions.

- Language for everything you write to {{owner_name}}: **{{language}}**. Code, file names and frontmatter keys stay in English.
- Timezone for dates, due dates and log timestamps: **{{timezone}}**.
- Who {{owner_name}} is and how they like to work: `.claude/rules/persona.md`. How you behave: `.claude/rules/soul.md`. Business facts: `.claude/rules/context.md`. If one of these is empty, run `/setup` before anything else.

## The five rules you never break

1. **No evidence, no close.** A task becomes `done` only with `evidence:` (file path, link, test output, screenshot). "Should work" is not evidence.
2. **A refusal is a STOP.** When a permission prompt, classifier or tool refuses a step, stop that step and report what you wanted to do and why. Never reach the same goal by another route.
3. **Never delete user files.** Move old versions to `old/YYYY-MM-DD/HHMMSS_<name>`.
4. **One owner per task.** A role or `human`. Never "we".
5. **Waiting on a human is always a task.** `status: blocked` requires `unblocked_by:` pointing to an `H-` task the human can finish in 15 minutes or less.

The full rule set, each with the incident that produced it, lives in `.claude/rules/01-work.md` to `05-projects.md`. Those files load into every session.

## Workspace map

```
CLAUDE.md                 this file
agentos.toml              config: owner, language, queue profile, WIP limit, notifications
.claude/agents/           ceo, marketing, copy, web, soft, research
.claude/rules/            the rules (auto-loaded) + persona, soul, context
.claude/skills/           setup, new-project, project, agent-queue, create-task, end, ...
projects/<slug>/          PROJECT.md  PLAN.md  LOG.md  tasks/  materials/
projects/.templates/      templates for every file above; always start from them
projects/dashboard.md     GENERATED, never edit
inbox/                    ad-hoc tasks for the agent, outside any project
ideas/                    ideas, not yet work
TODO.md                   human view; the block between AGENTOS markers is generated
.agentos/                 runtime state (logs, locks). Do not edit by hand.
```

## How work flows

1. **Project.** `/new-project` asks for the goal, a measurable success criterion with a date, constraints and what is out of scope, then writes `PROJECT.md`. Nothing gets planned without a success criterion.
2. **Plan.** The `ceo` role writes `PLAN.md` (3 to 6 phases) and the first batch of tasks, never more than `wip_limit` active agent tasks.
3. **Execution.** The queue (`{{engine}} run`, scheduled or on demand) picks one task, locks it, runs the owning role, logs every step in `## Progress log`, unlocks. In a live session `/agent-queue` does the same by hand.
4. **Human work.** Anything only {{owner_name}} can do becomes an `H-` task: 15 minutes or less, with a first step that takes 1 to 3 minutes ("open file X", "log in to Y").
5. **Decisions.** A choice that only {{owner_name}} can make becomes a separate `type: decision` task with a ready recommendation and its cost in `## For approval`. One question per decision.
6. **Review.** After a batch closes, or when a project stalls, the `ceo` runs a review (`type: review`): checks evidence, counts stalls, updates `LOG.md`, adds the next batch.
7. **Guard.** `{{engine}} guard` runs on schedule and repairs illegal states: a blocked task without an unblocking human task gets one; an accepted decision without an executing task gets one.

## Task files

Path: `projects/<slug>/tasks/<ID>-<kebab-slug>.md`. Inbox tasks: `inbox/<kebab-slug>.md`.
IDs: `A-001` for agent tasks, `H-001` for human tasks. Next ID = highest number in the whole `tasks/` directory + 1, counting both prefixes. Never reuse an ID.

Key fields: `owner`, `type` (`task|decision|review`), `status` (`todo|in_progress|blocked|done|cancelled`), `blocked_by`, `unblocked_by`, `decision`, `evidence`, `lock`, `autonomy` (`ask` = the queue skips it), `source` (`external` = always the safe profile). Full schema in `projects/.templates/task-agent.md`.

Sections, in this order when present: `## Goal`, `## Context`, `## Steps`, `## Definition of done`, `## For approval`, `## Unblocking action`, `## Owner notes`, `## Progress log`.

**Before acting on or closing any task, read the latest entry in `## Owner notes`.** It can change the scope. A later note beats an earlier plan.

## What needs {{owner_name}}'s approval

Always, regardless of standing permissions:
- anything irreversible (deleting data, force operations, dropping tables);
- anything that spends money or ad budget;
- mass sends (mailing to a list, bulk messages);
- publishing in {{owner_name}}'s name or a brand's name;
- changes to systems maintained by someone outside this workspace.

Not a decision: a push or deploy that meets the standing conditions (tests green before, verification after, report written). Pick the time window yourself and say what you did.

## Commands

The engine is installed in this workspace's own virtual environment, `.agentos/venv`. Run it from the workspace root as `{{engine}}` (Windows: `.agentos/venv/Scripts/python -P -m agentos`, macOS/Linux: `.agentos/venv/bin/python -P -m agentos`). Never use a bare `python -m agentos`: the system Python does not have the engine, and `-P` keeps files in this folder from shadowing it. Without a shell (the queue's `safe` profile) skip these commands; the scheduled job refreshes the views.

```
{{engine}} dashboard     regenerate projects/dashboard.md and the TODO.md block
{{engine}} guard         repair illegal states (idempotent)
{{engine}} status [slug] quick text status
{{engine}} run           run one task from the queue
{{engine}} doctor        check the installation
```

## Conventions

- Markdown with YAML frontmatter; checkboxes as `- [ ]` / `- [x]`. Works in any editor, including Obsidian.
- Dates `YYYY-MM-DD`, log lines `- YYYY-MM-DD HH:MM — what happened, where the evidence is`.
- Create tasks with `/create-task`, ideas with `/add-idea`, projects with `/new-project`. Do not hand-write files that a skill creates.
- Dashboards and the `TODO.md` block are generated. Never edit them.
- At the end of a session run `/end`: every instruction from {{owner_name}} has a task file, logs are written, worktrees and background processes are cleaned up.
