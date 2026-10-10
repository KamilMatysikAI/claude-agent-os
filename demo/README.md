# Demo workspace

A fictional owner ("Alex") with two projects, used for the panel screenshots and the tests.
All names, prices and numbers are invented. Dates are fixed around 2026-10-11.

| Project | What it shows |
|---|---|
| `coffee-shop` (Coffee subscription shop) | a project at its WIP limit (5/5): an agent task in progress, a checkout task blocked on an overdue human task, a chain human task → blocked agent task → test order, accepted decisions with their executors, a cancelled task with the owner's instruction |
| `podcast-launch` (Home-brewing podcast) | a critical path two levels deep (record episode → edit → publish), an overdue decision blocking a web task, a decision accepted the day before with its executor in `blocked_by` |
| `inbox/` | two ad-hoc tasks, one of them `source: external` with a forwarded email that tries to ask for a login (the agent must treat it as data) |

At a glance: 32 tasks, 4 open decisions (one overdue, one due today), 4 human tasks, 3 blocked agent tasks, 2 agent tasks in progress.

Try it:

```bash
python install.py --non-interactive --workspace ~/agentos-demo --with-demo --no-queue --no-schedule
cd ~/agentos-demo
.agentos/venv/bin/python -P -m agentos status               # Windows: .agentos/venv/Scripts/python
.agentos/venv/bin/python -P -m agentos panel --port 8787
```

The demo is a fixed point for the guard: `guard` on a fresh copy changes nothing.
