---
name: setup
description: One-time interview that tailors this workspace to its owner. Asks about the owner, their business, how they like to work and how the AI should behave, then fills .claude/rules/persona.md, soul.md, context.md and agentos.toml, and optionally switches on the scheduled queue and the panel. Use when the user types "/setup", says "set up the workspace", "configure the agents for me", "onboard me", or when persona.md / soul.md / context.md are still empty templates.
argument-hint: "[optional: section to redo — persona | soul | context | config | schedule]"
disable-model-invocation: true
allowed-tools: ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "AskUserQuestion", "Skill"]
---

# /setup — tailor the workspace to its owner

An interview of about 15–20 minutes. Output:

| File | What it holds |
|---|---|
| `.claude/rules/persona.md` | who the owner is, how they work, how they want to be spoken to |
| `.claude/rules/soul.md` | how the AI behaves with this owner, written in first person |
| `.claude/rules/context.md` | business facts: what the company does, customers, channels, stack, current projects |
| `agentos.toml` | `owner_name`, `language`, `timezone` (+ queue/panel switches if the owner wants them) |
| `CLAUDE.md` | leftover `{{owner_name}}` / `{{language}}` / `{{timezone}}` / `{{engine}}` placeholders filled in |

All three rule files load into every session automatically, so what you write here shapes every later answer. Keep them short and concrete.

Talk to the owner in the language they write in. Once `language` is set in `agentos.toml`, use that.

## Shared pattern: generate → show → revise → save

Used for persona, soul and context:
1. Generate the file from the interview answers only.
2. Show the full content.
3. Ask: "Read it and tell me what to change."
4. Revise and show again as many times as needed.
5. Save only after an explicit OK.

## Step 0: Safety check (never overwrite silently)

1. Find the workspace root: the directory with `agentos.toml` (walk up from the current directory). If there is none, stop and tell the owner to run the installer first (`python install.py` from the package checkout), then come back.
2. For each of `persona.md`, `soul.md`, `context.md` in `.claude/rules/`, decide whether it is still a template: it is a template when it still holds the guidance comments (`<!-- ... -->`) or `{{` placeholders and has no real content under its headings.
3. If a file already has real content, ask per file: **keep**, **update** (merge new answers into it) or **replace** (move the current file to `.claude/rules-archive/YYYY-MM-DD/HHMMSS_<name>` first, then write). Never delete, never overwrite without that answer.
4. If the argument names a section (e.g. `/setup soul`), run only that part.

## Step 1: Intro

Plain text, no question tool:

> We are going to set this workspace up for you. I will ask a few rounds of questions, then write three short files that every agent reads before it works: your profile, how I should behave with you, and your business context. At the end you can switch on the scheduled queue. About 15–20 minutes.

## Step 2: Who you are (open question)

> Tell me about yourself: what you do, what company or project, and how you got here. I want the path, not a one-liner.

Too short → ask once for more ("What did you do before this?").

## Step 3: Communication style (AskUserQuestion, 4 questions, single-select)

| Question | Header | Options |
|---|---|---|
| How formal should I be? | Formality | Casual (1–2/5) · Neutral (3/5) · Professional (4–5/5) |
| How do you make decisions? | Decisions | Gut feeling · Mixed: data where it matters · Data first |
| How do you want answers? | Format | Short, just the substance · Options with trade-offs · Examples first · Detailed |
| How do you want feedback? | Feedback | Blunt · Constructive: problem + fix · Gentle |

## Step 4: Values and work (one open question)

> 1. What rules do you always follow at work?
> 2. What do you never accept?
> 3. Which tools do you use every day?
> 4. What are you working on right now?

Generic answer → ask for one concrete example.

## Step 5: Relationship with AI (AskUserQuestion + open question)

Single-select: *How do you see the AI?* — Partner (has opinions, calls out mistakes) · Tool (does what I say) · Mentor (leads and teaches) · Assistant (supports and executes).

Then:

> 1. What annoys you in AI assistants? (e.g. "opens with 'Great question!'", "writes too much", "has no opinion")
> 2. How should *your* AI talk to you?

## Step 6: Energy and blockers (open question + one choice)

> 1. When are you in flow? Name at least three situations.
> 2. What drains you?
> 3. What gets in your way? (perfectionism, procrastination, too many ideas…) Be honest; it stays in this workspace.

Single-select: *Do you have personality test results (any framework)?* — Yes, I'll paste them · No. If yes, wait for the paste.

## Step 7: Write persona.md

Read `references/persona-guide.md`. If `.claude/rules/persona.md` is a template, keep its headings and fill them; otherwise use the structure from the guide. Apply generate → show → revise → save.

## Step 8: Business context (optional)

Single-select: *Add business context? Agents plan much better with it.* — Yes · Skip for now.

If yes:

> 1. What does the business do? (industry, model, rough scale)
> 2. Who are the customers?
> 3. Which sales and marketing channels do you use?
> 4. What is your tech stack?
> 5. Any systems maintained by someone outside this workspace (an agency, a contractor)? Agents will only read those, never change them without your approval.

Read `references/context-guide.md`, write `.claude/rules/context.md`, apply the shared pattern. If skipped, leave the template in place and say `/setup context` fills it later.

## Step 9: Write soul.md

AskUserQuestion, 2 single-select questions:

| Question | Header | Options |
|---|---|---|
| Humour and swearing? | Humour | Full: humour, swearing when it fits · Humour, no swearing · Strictly professional |
| Should I hold strong opinions? | Opinions | Strong: call out mistakes, no yes-man · Balanced: recommend, don't push · Neutral: facts, you decide |

Then open: *Describe in your own words the character your AI should have* (e.g. "a senior mentor who doesn't spare criticism but always brings a fix").

Read `references/soul-guide.md`. Generate from persona.md + context.md + these answers. Apply the shared pattern.

## Step 10: Config (agentos.toml)

Ask only what is missing or still default:
- `owner_name` — how agents address the owner.
- `language` — the language agents write to the owner in (ISO code, e.g. `en`, `de`, `pl`).
- `timezone` — IANA name (e.g. `Europe/Berlin`). Suggest the system timezone if you can read it.

Edit only these keys in place with `Edit`; keep comments and every other key as they are. Then replace any leftover `{{owner_name}}`, `{{language}}`, `{{timezone}}` placeholders in `CLAUDE.md` with the same values (and only those placeholders). A leftover `{{engine}}` (in CLAUDE.md or any skill) becomes `.agentos/venv/Scripts/python -P -m agentos` on Windows or `.agentos/venv/bin/python -P -m agentos` on macOS/Linux.

## Step 10b: Optional rule packs

Optional rules live in `.claude/rules-optional/` and are **not** loaded until copied into `.claude/rules/` (everything in `.claude/rules/` loads into every session, so only enable what applies). List the files there with a one-line description each (read the first lines of each file). Currently shipped:

| File | Enable when |
|---|---|
| `web.md` (W1–W4) | agents build or edit websites or a CMS |
| `sales.md` (S1–S4) | agents write sales material or run anything customers pay for |

AskUserQuestion, multi-select: *Which optional rule packs do you want?* (one option per file, plus "None").

For each chosen file: copy it from `.claude/rules-optional/<file>` to `.claude/rules/<file>` (read + write; keep the original in `rules-optional/`). If `.claude/rules/<file>` already exists, compare: identical → skip; different → ask keep/replace, and on replace archive the current one to `.claude/rules-archive/YYYY-MM-DD/HHMMSS_<file>` first. Never archive inside `.claude/rules/`: every file there, subdirectories included, loads into every session. Tell the owner where the archive is. To disable a pack later, move its file out of `.claude/rules/` the same way.

## Step 11: Scheduler and panel (optional, ask first)

Explain in two sentences: the queue runs one agent task every `interval_minutes` in the background under a permission profile; the default `safe` profile can read, write and search files in the workspace but cannot run shell commands or read secrets.

AskUserQuestion, single-select:
- **Not now** — everything works by hand with `/agent-queue` and `/project`.
- **Schedule the queue with the safe profile** (recommended).
- **Schedule the queue with the developer profile** — adds git status/diff/log and test runners; still no push, no `rm`, no `curl`.

The `full` profile is never offered here. It skips all permission prompts; the owner has to choose it in the installer, which asks for an explicit confirmation.

If the owner picks a schedule:
1. Set `[queue] enabled = true` and `profile = "<choice>"` in `agentos.toml` (edit in place).
2. Run `{{engine}} schedule install`, then `{{engine}} schedule status`, and show the result.
3. If the owner has the package checkout and prefers the installer, offer `python install.py --non-interactive ...` instead. Run `python install.py --help` first and use only flags that exist there. Never invent flags.

Panel: ask *Do you want the local web panel (kanban, decisions, "run now")?* If yes, set `[panel] enabled = true` and tell the owner to start it with `{{engine}} panel` (default `http://127.0.0.1:8777`).

Notifications: mention that `[notify]` supports `file` (a digest file) and `telegram`. Telegram credentials go **only** into `.env` (`AGENTOS_TELEGRAM_TOKEN`, `AGENTOS_TELEGRAM_CHAT_ID`), which the owner edits. Never ask the owner to paste a token into the chat; if they do, tell them to rotate it.

If a command is refused by a permission prompt or classifier: stop that step and report what you wanted to run and why. Do not try a different route to the same result.

Finish with `{{engine}} doctor` and show its summary.

## Step 12: Consistency check

Read the saved files and check:

| Check | Fix |
|---|---|
| soul.md reflects the preferences in persona.md (formality, format, feedback) | adjust soul.md |
| Everything the owner said annoys them in AI appears in soul.md "What I never do" | add the missing items |
| Tone of soul.md matches the chosen formality | adjust wording |
| No `{{` placeholders and no leftover guidance comments in CLAUDE.md, persona.md, soul.md, context.md | fill or remove; ask if unsure |

Small fixes: apply them and mention them. Larger contradictions: ask.

## Step 13: First project and wrap-up

1. Write `.agentos/setup-done` with `date: YYYY-MM-DD` (create `.agentos/` if missing). This only records that setup ran; re-running `/setup` is always allowed and goes through Step 0.
2. Ask: *Do you want to start your first project now?* If yes, invoke the `new-project` skill with the goal they describe.
3. Summary:

```
Workspace set up.

Files: .claude/rules/persona.md, soul.md, context.md (if written), agentos.toml
Rule packs: none | web.md, sales.md
Queue: off | scheduled every N min, profile <safe|developer>
Panel: off | on ({{engine}} panel)

Next:
1. /new-project — turn a goal into a plan and tasks
2. /agent-queue — run one agent task by hand
3. after a few sessions, /reflect — tune your profile from real conversations
```

## Constraints

- **Only the owner's words.** Persona, soul and context come from the interview. Nothing invented. Empty section beats a made-up one.
- **Review is mandatory** before any of the three files is saved.
- **Never overwrite** an existing non-template file without the keep/update/replace answer; "replace" archives to `.claude/rules-archive/` first.
- **No secrets in chat or files.** Credentials belong in `.env`, which the owner edits by hand.
- **Never offer the `full` profile** from this skill.
