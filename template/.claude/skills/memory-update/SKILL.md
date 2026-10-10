---
name: memory-update
description: Reads recent Claude Code session logs for this workspace, extracts facts (projects, decisions, priorities, blockers, stack changes) and merges them into .claude/rules/now.md — a short "current context" file loaded into every session. Task statuses come from the task files via the engine, never from conversation memory. Use for "/memory-update", "update now.md", "refresh the current context", "what have we been working on", or on a schedule after working sessions.
allowed-tools: ["Read", "Edit", "Write", "Bash", "Glob", "Grep"]
---

# /memory-update — keep the current context current

`.claude/rules/now.md` is loaded into every session, so every agent starts knowing what is going on right now. This skill rebuilds it from what actually happened in recent sessions and from the task files.

Two sources, two jobs:
- **Session logs** → decisions, new projects, blockers, stack changes (what was *said*).
- **Task files via the engine** → status, due dates, what is open or closed (what *is*). A conversation can be outdated within hours; the files are the truth (rule 3).

## 1. Time range

Read `.claude/rules/now.md` and take the timestamp from the line `*Last update: YYYY-MM-DD HH:MM*`.
- Timestamp found → parse sessions since then.
- No file or no timestamp → catch-up over the last 3 days. Create the file from the format in `references/merge.md`.

## 2. Parse the sessions

```
python .claude/skills/memory-update/scripts/parse_sessions.py --since "<timestamp>" --out .agentos/tmp/memory-update-dialog.txt
```

(or `--days 3` for catch-up). The summary line on stderr gives the session and message count. 0 sessions → say "No new sessions to analyse" and stop.

The script reads Claude Code's local session logs (`$CLAUDE_CONFIG_DIR/projects/` or `~/.claude/projects/`). It is read-only. The output file in `.agentos/tmp/` is overwritten on each run; it is runtime state, not user data.

## 3. Extract signals

Read `references/extract.md`, then the dialogue file. If it is long (over ~50,000 characters), work session by session. Produce the signal list as described there. Drop everything with LOW confidence.

## 4. Get the task truth from the engine

```
{{engine}} status
```

Use it for every task, due date and project status that will appear in now.md. For any `A-`/`H-` ID mentioned in the signals or already in now.md, the status comes from the engine output or the task file's frontmatter (`status`, `due`, `decision`, `closed`), not from the conversation. A task that is `done` or `cancelled` does not stay in now.md as open: remove it or mark it closed with the date.

If the CLI is unavailable, read the frontmatter of the referenced files directly (`projects/<slug>/tasks/<ID>-*.md`).

## 5. Merge into now.md

Read `references/merge.md` and apply its rules to the current now.md and the signals. Update the timestamp. Write the file.

## 6. Summary

```
Memory update — YYYY-MM-DD
Sessions: N | Owner messages: N

Added:    + [category] description
Updated:  ~ [category] description
Removed:  - [category] description (reason)
```

## Rules

- now.md: **max 120 lines**.
- Do not duplicate persona.md, soul.md, context.md or the rule files; they are loaded anyway.
- Facts and explicit statements only. No emotions, no guesses about intentions.
- Statuses and due dates from the files, never from the narrative.
- Fully automatic: write without asking for approval. Nothing is deleted except stale lines inside now.md, by the rules in merge.md.
