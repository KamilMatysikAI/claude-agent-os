---
name: new-project
description: Turns a goal into a project the agents can run on their own — a short dialogue about the goal, a measurable success criterion, constraints and what is out of scope, then projects/<slug>/ with PROJECT.md, LOG.md, tasks/ and materials/, and a first plan plus first batch of tasks from the ceo role for the owner to approve. Use for "/new-project", "new project", "start a project", "I want to build X, break it down", "plan this for me".
argument-hint: "[the idea in one sentence]"
allowed-tools: ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Agent", "AskUserQuestion"]
---

# /new-project — from an idea to a project that moves by itself

A project = goal + measurable success criterion + phases + tasks with one owner each. It lives in `projects/<slug>/`.

A one-off action ("call the supplier", "fix this typo") is **not** a project. Use `/create-task` for those. A project has a goal, phases and lives for weeks.

## Step 1: Pin down the goal (a dialogue, not a form)

Take as much as you can from what the owner already said and from `.claude/rules/context.md`. Ask **only** what is missing, at most 3 questions at once (AskUserQuestion when options make sense). Before any file is written, four things must be clear:

1. **Goal** — what should exist and why.
2. **Success criterion** — measurable and dated. "Grow sales" is not one; "10 paying customers by 2026-12-31" is. Without it the planner does not know when to stop. If the owner gives a threshold without a time unit ("20% margin"), ask over what period before writing it down.
3. **Constraints** — budget, deadline, people, tools, things that need approval.
4. **Out of scope** — what we are not doing. The cheapest way to keep a project from swelling. Ask when the scope sounds broad.

This is the one thing worth arguing about. **Do not create a project without a measurable success criterion.**

## Step 2: Create the structure

`<slug>`: kebab-case, ASCII only, short (`online-course`, `shop-relaunch`). If `projects/<slug>/` already exists, stop and ask: different slug, or work on the existing project with `/project <slug>`.

```
projects/<slug>/
  PROJECT.md     from projects/.templates/PROJECT.md
  PLAN.md        written by ceo in step 3
  LOG.md         from projects/.templates/LOG.md
  tasks/
  materials/
```

`PROJECT.md` frontmatter:

```yaml
---
slug: <slug>
name: <human-readable name>
status: active
owner_human: <owner_name from agentos.toml>
wip_limit: <[projects] wip_limit from agentos.toml, default 5>
created: YYYY-MM-DD
---
```

Sections: `## Goal`, `## Success criteria`, `## Constraints`, `## Out of scope`. Fill **every** section with content from the dialogue. No placeholders in the finished file. If a template is missing, write these sections yourself.

First `LOG.md` entry: `- YYYY-MM-DD HH:MM — project created. Goal: <one sentence>. Success: <criterion>.`

## Step 3: First plan (ceo)

Call the `ceo` agent (Agent tool, `subagent_type: "ceo"`) with this brief:

> Read `projects/<slug>/PROJECT.md` and `.claude/rules/context.md`. Write `projects/<slug>/PLAN.md` with 3–6 phases (each with an exit condition) and a "Risks" section. Create the first batch of tasks in `projects/<slug>/tasks/` from the templates in `projects/.templates/`, at most `wip_limit` active agent tasks. Agent tasks (`A-`) need `## Definition of done` and the evidence expected. Human tasks (`H-`) must take 15 minutes or less and start with a first step of 1–3 minutes. Every decision only the owner can make is its own `type: decision` task with a recommendation in `## For approval`, never a line in a list of questions. IDs: next ID = highest number in the whole `tasks/` directory + 1. Set `autonomy: ask` on every task in this first batch. Append one line to LOG.md.

If the Agent tool or the `ceo` role is not available, do the same yourself following `.claude/agents/ceo.md`.

## Step 4: The owner approves the first batch

The first batch always goes to the owner before anything runs. Show:
- phases, one line each;
- tasks: ID, owner, title, due date;
- what waits on the owner (H- tasks and decisions);
- the biggest risk.

On approval, switch the approved agent tasks to `autonomy: full`. Leave `autonomy: ask` on tasks that touch money, mass sends, publishing in the owner's name, or systems maintained by someone else. Rejected or changed tasks: edit them per the owner's comment, or set `status: cancelled` with the reason in `## Progress log`. Never delete task files. Log the approval in `LOG.md`.

Later batches are added by the ceo during reviews (`/project <slug> review`) without this approval step, still within `wip_limit`.

## Step 5: Refresh the views

```
{{engine}} guard
{{engine}} dashboard
```

`guard` creates any missing unblocking tasks; `dashboard` regenerates `projects/dashboard.md` and the generated block in `TODO.md`. If the command is unavailable or refused, say so in the report. Do not write the dashboard by hand.

Optional: for a high-stakes or hard-to-reverse project, suggest `/premortem <slug>` before work starts.

## Step 6: Report

Short, readable in 30 seconds: goal, success criterion, phases, first batch (who does what), what waits on the owner, the biggest risk.

## Rules

- No project without a measurable, dated success criterion.
- One owner per task: a role or `human`. Never "we".
- Human tasks: 15 minutes or less, first step 1–3 minutes. Longer human work gets split.
- Agent tasks: definition of done + required evidence.
