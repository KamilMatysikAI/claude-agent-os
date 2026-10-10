---
name: add-idea
description: Captures an idea as its own file in ideas/ with a short first analysis (first steps, upside, main risk), category, potential, effort and tags, then regenerates ideas/index.md. Also changes an idea's status (approve, reject, start, done) and can turn an approved idea into a project. Use when the user says "I have an idea", "what if we…", "note this idea", "save this for later", "idea:", "/add-idea", or "approve / reject / park the idea about X".
argument-hint: "<idea name> [| category] [| potential]"
allowed-tools: ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "Skill"]
---

# /add-idea — an idea is not work yet, but it is not lost either

Ideas live in `ideas/`, one file each. They are not tasks: nothing runs from here. An idea becomes work only when it turns into a project (`/new-project`) or a task (`/create-task`).

## 1. Load the config

Read `references/config.md`: categories, potential, effort, tags, statuses. The owner may have edited it; use what is there.

## 2. Parse the request

Format: `name | category | potential`, delimiter `|`. Only the name is required.

Defaults without asking: `category: other`, `potential: medium`, `effort: medium`. Take values from the owner's words using the hints in the config ("this would be huge" → `potential: high`).

## 3. File name

`ideas/<kebab-name>.md`: kebab-case, ASCII only, lowercase, max ~50 characters. If it exists, append `-2`, `-3`. Never overwrite.

Before creating, Grep `ideas/` for a similar title. If a near-duplicate exists, show it and ask: add to the existing idea (a dated line in its `## Notes`) or create a new one.

## 4. Write the idea

Start from `ideas/.templates/idea.md`. Frontmatter:

```yaml
---
title: <name>
status: new
category: <category>
potential: <low|medium|high>
effort: <low|medium|high>
tags: [tag1, tag2]
project:
created: YYYY-MM-DD
---
```

Then `# <name>` and the template's sections. Fill them from what the owner said, quoting their words where useful. Always write a **first analysis**, even if the owner gave only a name (2–4 sentences across the sections): possible first steps, the upside, the main risk or challenge. Mark estimates as estimates. Invent no numbers; leave a section empty rather than making things up.

## 5. Regenerate the index

```
python .claude/skills/add-idea/scripts/ideas_index.py
```

It rebuilds `ideas/index.md` grouped by status. Never edit the index by hand. Without Bash, say the index will be refreshed next time.

## 6. Confirm

```
Idea saved: ideas/<name>.md
Category: <category> · Potential: <potential> · Effort: <effort>
Tags: <tags>
First step if you pursue it: <one line>
```

## Changing an idea's status

"approve the idea about X", "reject X", "we're doing X", "X is done":
1. Find the file (Glob/Grep in `ideas/`).
2. Update `status` (`analysing`, `approved`, `in_progress`, `done`, `rejected`).
3. Add a dated line to `## Notes` with the reason, especially for `rejected`. A rejected idea with its reason prevents the same discussion next month.
4. Files stay in `ideas/`; nothing is moved or deleted.
5. Regenerate the index.

Turning it into work:
- Large (goal, phases, weeks) → offer `/new-project`, passing the idea file as context. Then set `status: in_progress` and `project: <slug>`.
- Small (one action) → offer `/create-task`. Then `status: in_progress` and a note with the task ID.

## Constraints

- Never create an idea without a name; never overwrite or delete a file.
- Dates `YYYY-MM-DD`.
- `project:` is a bare project slug or empty.
