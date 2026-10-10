---
name: create-task
description: Creates a task file (agent task, human task, decision, or ad-hoc inbox task) with the right ID, frontmatter and sections, or updates an existing one (due date, priority, status, owner note, close with evidence). Use when the user asks to add a task, "remind me to", "put this on the list", "add a todo", "the agent should do X later", "I need to decide X", or "move the due date", "change priority", "close task", "cancel task".
argument-hint: "<title> [| owner] [| due] [| project-slug]"
allowed-tools: ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]
---

# /create-task — one file per piece of work

Every instruction from the owner that is not done in this session becomes a task file **in this session** (rule 7). A commitment that lives only in a chat or a notes file gets lost.

## 1. Parse the request

Argument format: `title | owner | due | project`, delimiter `|` (commas may appear in titles). Everything is optional except the title. Also take values from the sentence itself:

| The owner says | Field |
|---|---|
| "urgent", "asap", "blocking" | `priority: high` |
| "when you have time", "someday" | `priority: low` |
| "today", "tomorrow", "by Friday", a date | `due:` as `YYYY-MM-DD` (timezone from `agentos.toml`) |
| "you do it", "for the agent", "take it on" | agent task (`A-`) |
| "remind me", "I need to", "I have to call" | human task (`H-`) |
| "help me decide", "A or B?" | `type: decision` |
| a project name or slug | `project:` (must match a directory in `projects/`) |

Defaults without asking: `priority: normal`, no due date, `size: small`, `autonomy: full`, `source: local`.

Do not invent a project. If none is named and the task clearly belongs to one, check `projects/*/PROJECT.md` and use that slug; if unsure, ask once. A title is the only thing you must have.

## 2. Choose the kind

| Kind | Where | ID | Template |
|---|---|---|---|
| Agent task in a project | `projects/<slug>/tasks/<ID>-<kebab-title>.md` | `A-NNN` | `projects/.templates/task-agent.md` |
| Human task in a project | same directory | `H-NNN` | `projects/.templates/task-human.md` |
| Decision | same directory | `H-NNN`, `type: decision` | `projects/.templates/task-decision.md` |
| Review | same directory | `A-NNN`, `owner: ceo`, `type: review` | `projects/.templates/task-review.md` |
| Ad-hoc agent task, no project | `inbox/<kebab-title>.md` | none, `project:` empty | `projects/.templates/task-agent.md` |
| Personal to-do, no project | a checkbox line in `TODO.md` **outside** the `<!-- AGENTOS:START -->`…`<!-- AGENTOS:END -->` block | none | none |

Agent owner: pick the role from the work (`copy` texts, `web` pages, `soft` code and integrations, `marketing` campaigns and channels, `research` facts and analysis, `ceo` planning and reviews). One owner, never "we".

## 3. ID and file name

Next ID: highest number in the **whole** `projects/<slug>/tasks/` directory (subdirectories and archived files included, both prefixes) + 1. Compute it, do not guess:

```
python .claude/skills/create-task/scripts/next_id.py <slug> A
```

If Bash is unavailable, Glob `projects/<slug>/tasks/**/*.md`, read the numbers from file names and `id:` lines, and add one. Never reuse an ID, even of a cancelled task.

File name: `<ID>-<kebab-title>.md`; kebab-case, ASCII only, lowercase, max ~50 characters. Inbox: `<kebab-title>.md`. If the file exists, append `-2`, `-3`. Never overwrite.

## 4. Fill the file

Start from the template; if it is missing, use this skeleton. Frontmatter keys exactly as below.

```yaml
---
id: A-012
project: <slug>          # empty for inbox
title: <title>
owner: copy              # ceo|marketing|copy|web|soft|research|human
type: task               # task|decision|review
status: todo
priority: normal         # high|normal|low
due:                     # YYYY-MM-DD or empty
created: YYYY-MM-DD
closed:
size: small              # small|medium|large
autonomy: full           # full|ask
source: local            # local|panel|external
profile:
blocked_by: []
unblocked_by:
decision:
evidence:
lock:
---
```

After the frontmatter, an H1 with the title (`# <title>`). Then sections in this order, only those that apply: `## Goal`, `## Context`, `## Steps`, `## Definition of done`, `## For approval`, `## Unblocking action`, `## Owner notes`, `## Progress log`.

Per kind:
- **Agent task:** `## Steps` written out from what is known (never empty), `## Definition of done` naming the evidence expected (file, link, test). Set `autonomy: ask` when the task touches money, mass sends, publishing in the owner's name, or a system maintained by someone else. `size`: small < 15 min, medium 15–60 min, large > 60 min.
- **Human task:** must fit in 15 minutes (`[projects] human_task_max_minutes`). The first step takes 1–3 minutes and is physical ("open <file>", "log in to <service>"). Longer work → split into several `H-` tasks or let an agent prepare everything first.
- **Decision:** one question per task. `## For approval` holds the recommendation, its cost and what happens after acceptance; alternatives below with one line each. Never put a decision as an item in a list of questions.
- **Inbox:** `project:` empty, `id:` empty; the file name identifies it. Other tasks refer to it (`blocked_by`, `unblocked_by`) by file name without `.md`.
- **Waiting for a date:** never a step like "do not start before X" (rule 36). Put the date in `due:` of a human task the agent task is `blocked_by`, or leave the task in `PLAN.md` for the ceo to create on time.

Due date in the past → create anyway and warn.

## 5. Refresh views

```
{{engine}} dashboard
```

Never edit `projects/dashboard.md` or the generated block in `TODO.md` by hand. If the CLI is unavailable, say the dashboard will refresh on the next scheduled run.

## 6. Confirm

```
Task created: <ID> <title>
File:     <path>
Owner:    <owner>   Priority: <priority>   Due: <date or none>
Next:     <who does what first>
```

## Updating an existing task

Find the file (by ID with Glob `projects/*/tasks/<ID>-*.md`, or by title with Grep).

| Request | Change |
|---|---|
| move due date | `due:`; if it is the third move, say so: a task moved three times needs a decision, not a new date |
| change priority | `priority:` |
| owner comment | append to `## Owner notes`: `- YYYY-MM-DD HH:MM — <text>` (latest note wins over earlier plans) |
| start / pause | `status: in_progress` / back to `todo`, with a log line |
| block | `status: blocked` + `unblocked_by: H-xxx` (create that human task) + `## Unblocking action` |
| close | only with `evidence:` (path, link, test output) + `closed: YYYY-MM-DD` + final log line. No evidence → it stays open; say what is missing |
| cancel | `status: cancelled` + `closed:` + reason in `## Progress log`. Human tasks are cancelled or merged only on the owner's own instruction |
| accept / reject decision | `decision: accepted|rejected`, `status: done`, `closed:`, note in `## Owner notes`. The guard then creates the executing task for an accepted decision |

Every change gets a line in `## Progress log`. Then `{{engine}} dashboard`.

## Constraints

- Never create a task without a title, never overwrite a file, never delete one.
- Dates always `YYYY-MM-DD`.
- `project:` is a bare slug matching a directory in `projects/`, or empty. Not a link, not a display name.
