---
name: end
description: Closes a working session with the owner — checks that everything the owner asked for is done or written down as a task (task files, logs, git, worktrees, background processes, secrets), records the session status, then proposes at most 3 improvements to the system (FIX / IMPROVE / BREAKTHROUGH) for the owner to pick by number. Use for "/end", "are we done?", "did we finish everything?", "wrap up", "close the session", "let's stop here".
argument-hint: "[optional: what to pay attention to]"
allowed-tools: ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "Skill"]
---

# /end — close the session

Two parts, always in this order:
1. **Clean-up** — answer "did we finish everything?" and record the status.
2. **System improvement** — at most 3 proposals; nothing is applied without a number from the owner.

Only for sessions with a human. A headless run (the queue, a subagent) does not run `/end`: nobody is there to pick a number, and proposals from dozens of runs a day are noise.

## Part 1. Clean-up

### 1.1 The owner's instructions in this session

Go through the whole conversation from the start. List **every** instruction from the owner, including ones thrown in passing ("and while you're at it…"), each with a status:
- **done** + evidence (path, ID, test output, link). No evidence, no "done".
- **partial** — what is left.
- **not started**.
- **waiting on the owner** — exactly on what.

Judge by the **latest** instruction in each thread (rule 5). A correction halfway through the session changes what "done" means.

### 1.2 Technical state

Check only what the session touched:
- **git**: in every repo with changes, `git status --short`, uncommitted files, unpushed commits (`git log @{u}..` when there is an upstream). Commit only by explicit file names, never `git add -A` in a shared repo; push only under the owner's standing rules.
- **worktrees**: `git worktree list`. Worktrees created in this session and already merged → `git worktree remove <path>` (never `--force`; if git refuses because of uncommitted changes, commit them or report them) and delete the merged branch. Report "worktree removed: yes/no + why" (rule 23).
- **background processes**: dev servers, watchers, daemons started in this session. Stop only your own, never by global name.
- **deploys**: if there was one, is there a verification after it (health check, version), not just "pushed"?
- **scratch files**: temporary scripts left in project directories → move to a scratch location or keep deliberately. Do not delete user files.
- **outgoing drafts** created in this session (mails, posts): where are they, are they waiting for a send decision?
- **secrets**: did a key, password or token pass through the chat or a command line? Then it must be rotated now; note it as a task if the owner has to do it.

### 1.3 Record the status

In this order:
1. **The task we worked on** (`projects/*/tasks/*.md`, `inbox/*.md`) → line in `## Progress log`, ticked steps, `status` matching reality. Close only with evidence.
2. **Project `LOG.md`** → the owner's decisions from this session, one dated line each.
3. **Unfinished work without a task file** → create one now with `create-task` (agent or human). An open thread without a file is lost (rules 6 and 7).
4. **Session note** → append to `notes/sessions/YYYY-MM-DD.md` (create it with `# Sessions — YYYY-MM-DD` if missing):

```markdown
## HH:MM — <session title, 3–5 words>

- done: <item> — <evidence>
- open: <item> — <where it is tracked: task path>

---
```

Then run `{{engine}} dashboard` so the views match the files.

### 1.4 Clean-up report

```
## Did we finish?

<YES, everything closed | NO, N things left>

| # | Instruction | Status | Evidence / where tracked |
|---|---|---|---|

Cleaned up: <what you did yourself in 1.2–1.3>
For you:    <only what needs the owner — concrete, with the first step>
```

Close what you can without the owner right away (log lines, removing a merged worktree, stopping your own process, committing by file name). Inside clean-up you never do anything that needs approval: deploys outside standing permission, sends, deletions, pushes the owner has not allowed.

## Part 2. System improvement

### 2.1 Material

The whole conversation: the owner's corrections, repeated questions, mistakes, workarounds, manual steps, "why not just…" moments. Plus the files changed in the session (git diff, new files).

### 2.2 Pick ONE mode

- **FIX** — something went wrong or the owner had to correct you. Goal: it never happens again.
- **IMPROVE** — the result was good, but there was friction (questions, manual steps, searching, repetition).
- **BREAKTHROUGH** — a new, large opportunity for the system or the business is visible.

Precedence: FIX > IMPROVE > BREAKTHROUGH. One correction from the owner is enough for FIX.

### 2.3 Check it is not already there

Before proposing anything, Grep `CLAUDE.md`, `.claude/rules/`, the touched skills' `SKILL.md`, and open tasks in `inbox/`. If the rule exists and was broken anyway, the problem is enforcement, not a missing rule: propose an automatic check (a hook, a validator, a test), not another paragraph of instructions.

### 2.4 Proposals

At most 3, each one of four types: **test**, **automatic check** (hook, validator, guard rule), **simpler step** (script, skill, shortcut), **better instruction** (CLAUDE.md, rules, SKILL.md).

```
## System improvement — mode: <FIX | IMPROVE | BREAKTHROUGH>

Why this mode: <one sentence pointing at a concrete moment in this session>

1. * <type> — <what exactly, in which file> — <which problem from this session it closes> — <cost: minutes / a task>
2. <type> — …
3. <type> — …
0. No changes

Pick a number.
```

`*` marks the recommended one; exactly one. Concrete, never "could be improved": file name, rule, test.

### 2.5 After the pick

- **0** → done.
- **Small change** (up to ~30 min, no production impact) → apply it now. A new instruction gets a line `**Why:** YYYY-MM-DD — <what happened in this session>`. An automatic check gets a test.
- **Large change** → a task via `create-task`, quoting the moment from the session in `## Context`.
- Add the choice to this session's entry in `notes/sessions/YYYY-MM-DD.md`: `- /end: mode X, picked N → <file / task>`. Insert it **inside the session entry, before its closing `---`**, not at the end of the file.

## Rules

- Nothing from part 2 is applied before the owner picks a number.
- The approval rules in `CLAUDE.md` (irreversible actions, money, sends, outside-maintained systems) win over anything here.
- Observations about the owner (preferences, style) belong to `/reflect`. If there are some, add one line: "There are also observations for your profile — run /reflect?".
- Short. The clean-up report and proposals fit on one screen.
