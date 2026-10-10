# 03 · Automation that fails safely

Before you ship any automation, script or workflow, ask one question: **what happens when one step fails in the middle of a batch?** Does only that item fail, or the whole run? Are the "sent" / "processed" flags still right? Does the failure cause a retry loop?

---

## 16. Fail per item, not per batch

**Rule.** Wrap each item in its own error handling, not the whole loop. Make operations idempotent: set state flags the same way every time (always before the action, or always after). Validate input before it reaches an external API. Every error lands somewhere a human will see it (a field, a log file, an alert).

**Why.** One email address with a typo in the domain stopped an entire batch. The default "stop on error" meant the "sent" flags were never set, so the next run sent everything again. Ten failed runs in five hours; customers received a dozen duplicates.

**How to apply.**
- Workflow tools: email, HTTP and API steps set to "continue on error"; the failed item still gets its "processed" flag plus an error field.
- Python/JS: `try/except` (or `try/catch`) inside the loop body.
- Reject malformed emails, empty required fields and invalid URLs before sending.
- Test with one deliberately broken record before going live.

## 17. Interfaces with a hard timeout queue long work

**Rule.** Where a time limit exists (chat bot, webhook, HTTP request), long work goes into a queue and runs locally without the limit. The user gets an immediate acknowledgement and a report after the fact.

**Why.** A chat bot with a 300-second timeout started long jobs inline. Jobs cut off halfway left inconsistent state: half-written files, tasks marked as started that never finished.

**How to apply.** If a job might exceed half the timeout, it is queued. Never "let's try, maybe it fits".

## 18. Automation is quiet

**Rule.** Notifications carry effects only (finished tasks, real changes), batched into a digest two or three times a day. Technical failures (rate limit, timeout, session error) go to the log, plus one line in a daily summary. Only something that needs a human decision goes out immediately. Deduplicate notifications in a way that survives changing timestamps.

**Why.** One night the queue sent seven identical "limit reached" alerts, one per run. The owner stopped reading alerts, including the ones that mattered.

**How to apply.** Write notifications for a non-technical reader: what got done, what waits for them and why. No internal jargon (locks, profiles, frontmatter states). An empty run costs nothing and sends nothing.

## 19. An isolated environment, never the interpreter from PATH

**Rule.** Every script runs with the project's own environment (`.venv` for Python, the project's `node_modules`). Never with whatever `python` is first on PATH. Dependencies are listed in a requirements file and installed into that environment.

**Why.** An operating system update put a new Python version first on PATH. Twenty-one scheduled jobs started running an interpreter with no packages; a watchdog restarted the main bot in a loop for hours. Nothing alerted, because each failure looked like a normal restart.

**How to apply.** Scheduled jobs store the full interpreter path chosen at install time. `{{engine}} doctor` checks it.

## 20. Recurring work has an executor

**Rule.** A recurring commitment ("every Monday", "each issue", "monthly report") is written in `PROJECT.md` with its rhythm and its executor: a scheduled job, or a chain of tasks where closing one cycle creates the next.

**Why.** After the first issue of a weekly publication went out, the planner opened a hundred-plus tasks on new features in one week. None of them was the next issue. The rhythm existed only in people's heads, and the gap surfaced when the owner asked about it.

**How to apply.** Before any batch of "expand the product" tasks, check that the next window of every active cycle has an executor. If not, that task goes first.

## 21. Retries and pauses are explicit

**Rule.** When a run hits a usage limit, it records the reset time in a state file and pauses until then. It does not retry every interval, and it does not alert on every attempt.

**Why.** The night of seven identical alerts (rule 18) came from a queue that simply tried again on every interval against a limit that would not reset for hours. Each attempt was wasted, and each one alerted.

**How to apply.** Detect the limit message once, write `paused_until`, exit cleanly, release the lock.

## 22. A push or deploy that meets the conditions is not a decision

**Rule.** Pushing or deploying with green tests before, a verification step after (health check, version) and a written report is covered by the owner's standing approval. If the only question is "when", pick the window yourself and describe the risk in the report. Always needs explicit approval: irreversible operations, anything that spends budget, mass sends, systems with an outside maintainer (rule 15).

**Why.** A release with 50+ commits and over a thousand passing tests still became a decision task because of a weekend timing question. It consumed one of the owner's scarce decision slots for something with an obvious answer.

**How to apply.** Write the standing approval and its exceptions in `context.md`. If tests are red, there is no deploy and no decision: fix first.
