# Extracting signals from the session dialogue

Read the dialogue and pull out signals: concrete, factual information about what the owner is working on, what they decided and what is blocking them.

## Categories

1. **PROJECTS** — new projects, status changes, finished projects.
2. **DECISIONS** — explicit decisions by the owner (technical, business, organisational).
3. **PRIORITIES** — what the owner named as important, urgent, or with a deadline.
4. **BLOCKERS** — technical problems, things that do not work, dependencies holding up progress.
5. **STACK** — new tools, dropped tools, configuration changes, new integrations.
6. **PATTERNS** — recurring behaviour or organisational preferences, ONLY if confirmed in at least 2 sessions.

## Output

A JSON array:

```json
[
  {
    "category": "DECISIONS",
    "type": "NEW",
    "content": "Newsletter moves from weekly to every two weeks starting next month.",
    "quote": "let's send it every two weeks from now on",
    "confidence": "HIGH",
    "task_ids": []
  }
]
```

- `category`: one of the six above.
- `type`: `NEW` | `UPDATE` | `FINISHED` | `REMOVE`.
- `content`: 1–2 sentences, specific.
- `quote`: the owner's exact words when there is an explicit statement, else `null`.
- `confidence`: `HIGH` | `MEDIUM`.
- `task_ids`: any `A-`/`H-` IDs the signal refers to (their status is checked later against the files).

## Confidence filter

- **HIGH** — the owner said it directly (there is a quote).
- **MEDIUM** — clearly follows from the work done (e.g. a whole session spent on X).
- **LOW** — interpretation or guess → **drop it, do not return it**.

## Never extract

- The owner's emotional state (frustration, joy, fatigue, stress).
- Speculation about intentions ("plans to", "is considering dropping").
- Judgements about the quality of the owner's work.
- One-off technical instructions ("fix this bug", "change the colour").
- System commands and their output.
- Anything already in persona.md, soul.md or context.md (stable traits and facts).
- Secrets, credentials, personal data of third parties.

## Hints

- Facts and explicit statements first.
- "We're dropping tool X" = OK (HIGH, quoted). "Seems unhappy with tool X" = forbidden.
- The owner worked on a project without talking about it → MEDIUM (the fact that it was worked on).
- Fewer high-quality signals beat many weak ones.
- A session spent debugging one bug → extract the blocker (or that it was resolved), not a project.
