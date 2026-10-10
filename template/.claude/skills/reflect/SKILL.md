---
name: reflect
description: Learns from the current session. Pulls out observations about the owner (preferences, corrections, new facts) and about the AI's own behaviour, then proposes precise edits to .claude/rules/persona.md, soul.md and context.md, shown as a diff and applied only after approval. Use for "/reflect", "learn from this session", "update my profile", "remember how I like this", "calibrate yourself", or after a session with several corrections from the owner.
allowed-tools: ["Read", "Edit", "Glob", "Grep"]
---

# /reflect — the session teaches the system

Scan the current session and propose updates to the context files every agent reads. Small, verified edits beat large rewrites.

## 1. Load the files

```
.claude/rules/persona.md    the owner: style, values, work, blockers
.claude/rules/soul.md       the AI's character with this owner
.claude/rules/context.md    business facts
```

Note their section structure. If a file is missing or still a template, say so and suggest `/setup` for it instead of writing it here.

## 2. Load the mapping

Read `references/mapping.md`: which signals go to which file and section, with examples.

## 3. Scan the session

Look for the signals in the mapping. For every candidate, decide:

| Kind | Add? |
|---|---|
| Explicit: the owner said it directly | yes |
| Repeated: at least twice in this session, or also in earlier ones you can see | yes |
| One-off and implicit ("this time no emojis") | **no** |

Also skip anything already in the files (Grep first), anything about a single task rather than the owner, and anything emotional ("seemed frustrated"). Volatile numbers (balances, prices, statuses) never go into these files; they belong to the source systems.

Working rules ("always run tests before a deploy") belong in `.claude/rules/01-…05-*.md`, not in persona or soul. If the session produced one, propose it as a separate item and name the rule file; the owner decides.

## 4. Answer

**If there are observations:**

```
Observations from this session:

| # | Signal (quote or description) | File | Section | Type |
|---|---|---|---|---|
| 1 | "shorter, two sentences max" (said twice) | persona.md | 3. Communication style | UPDATE |

Proposed edits:

persona.md → 3. Communication style
- Preferred format: short, just the substance
+ Preferred format: two to three sentences unless asked to expand

Apply? (all / numbers / none)
```

**If there are none:**

```
No new observations. The session matches the profile.
```

## 5. After approval

- Edit only the approved items, with `Edit` (never rewrite whole files).
- Update the date line at the end of each changed file (`*Last edit: YYYY-MM-DD*`).
- If a fact in context.md was corrected, keep the old value out and add the date of the correction, so a later reader knows which version is newer.

## Rules

- Never edit without approval. Show the diff before editing.
- Never duplicate what is already there.
- Never record one-off preferences.
- Never infer emotions or intentions; record facts and explicit statements.
- Keep the files short (persona about 80 lines, soul 50–150, context as short as the facts allow). If an addition pushes a file past that, propose what to merge or remove.
