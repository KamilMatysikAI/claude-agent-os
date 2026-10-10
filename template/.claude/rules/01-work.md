# 01 · Work discipline

Every rule here was written after something went wrong in a real business run by agents (property development, online retail, rentals). Each rule has three parts: the rule, why it exists, how to apply it. Rules are numbered across all five files so they can be cited ("rule 14").

---

## 1. No evidence, no close

**Rule.** A task becomes `done` only when `evidence:` points to something a person can open: a file path, a link, a screenshot, a test result. Numbers and statuses are checked a second time by a script before you report them.

**Why.** A report gave a total that was off by thousands because it was added up in the model's head. A deploy watcher reported "deployed" by matching a word in a log while the service still ran the old version. A script "verified" an invoice by opening the wrong record. All three looked finished.

**How to apply.**
- "Should work", "looks good", "done" are not evidence. Paste the output of a fresh command.
- Sums: compute with a script, paste the script's result.
- Deploy status: read the health endpoint or version field, not log text.
- Records (invoice, task, recipient): confirm the ID, not the title.
- When the work touches money or production, end the report with a short `Checks` section listing what you verified and the result.

## 2. Reset after two failures

**Rule.** If an approach failed twice, stop. Say plainly what does not work and propose a different strategy. Do not try a third variation of the same idea.

**Why.** Agents left alone keep iterating on a broken idea with small changes, each attempt "almost" working, and burn hours and budget. The two-attempt cap was set after that pattern repeated across projects; a different method nearly always got further.

**How to apply.** Count attempts per approach, not per command. On the second failure write two lines in the task log: what failed and why you think so, and the new approach. If you see no other approach, the task goes `blocked` with a human task asking for a decision.

## 3. Data from the source, and a note is not the current state

**Rule.** Names, prices, descriptions, images and URLs come from the system that owns them (API, database, file), never from memory. Anything that changes (balances, prices, statuses, deadlines, "sent", "paid") is a hypothesis until confirmed at the source. When two records disagree, the newer dated one wins.

**Why.** A context file said a deal was active for a full day after it had been terminated, and work was planned on top of it. A watchdog reported a wrong balance for a week because it read its own earlier note instead of the account.

**How to apply.** Before acting on a changing fact, read it from the source in the same session and note in the log where you read it. If the source is unreachable, say so; do not fall back to the note silently.

## 4. Look it up before you ask the human

**Rule.** Before adding a question for the human, search three places: memory, the project's `LOG.md` / `PROJECT.md` / task files, and skill configs and references. Ask only when the answer is not there or the records contradict each other.

**Why.** In one review, 3 of 36 questions sent to the owner already had answers in the system (an account ID in a skill config, a mailbox status in memory, a cancellation already marked as sent in a project log). The owner spent time answering what the system knew.

**How to apply.** When you find the answer, use it and write in the task log where it came from (file and line), so the next session does not search again.

## 5. Read the latest owner note before acting or closing

**Rule.** Before you work on or close a task, read the newest entry in `## Owner notes`. A verdict lives with its data: when the owner adds documents or a comment after a verdict, the verdict is to be recalculated, not defended.

**Why.** A task was closed during an audit because every step was ticked, while the owner's last note said "come back after the import and recalculate". The recalculation never happened; the owner caught it himself.

**How to apply.** Make reading `## Owner notes` the first step of every run on a task. If the latest note changes scope, update `## Steps` before doing anything else, and log that you did.

## 6. A task with a remainder is not closed

**Rule.** If your log says "not verified", "for the owner to decide" or "next session", the task stays open until that remainder has its own task file and its ID is written in the log. An owner instruction added after closing reopens the task or gets its own file in the same session.

**Why.** Across five projects, tasks were closed with a dangling "still to check" line. The remainders were never picked up, because nothing in the queue pointed at them.

**How to apply.** Before setting `done`, search your own log for words like "later", "not checked", "to decide". Each hit becomes a task (`/create-task`) or is resolved now.

## 7. An instruction from the human is a task file, in the same session

**Rule.** Anything the human asks for (in chat, panel, email, voice note) ends as a task file before the session ends. Not a paragraph in `PLAN.md`, not a "working number", not a line in a notes file. Quote the instruction in `## Context`.

**Why.** Seven of the owner's own commitments lived only in a notes file; nobody forgot them, but no task existed, so work waited weeks. Elsewhere an instruction was accepted as "task 20", the file was never created, numbering moved on, and two weeks passed with no work.

**How to apply.** Close the conversation only when `ls projects/<slug>/tasks/` (or `inbox/`) shows the file. `/end` checks this.

## 8. Zero-cost known pattern: do it and tell

**Rule.** An action that meets all four conditions is done without a decision task: (a) it has a precedent in this project or a written rule, not reversed later; (b) it costs nothing; (c) it is reversible; (d) it does not touch money, customer data, ad accounts, mass sends, publishing in someone's name, or shared production infrastructure. Leave one line in the log naming the precedent.

**Why.** A zero-cost, reversible action that had been done before waited days for a click. After the click, nobody executed it, because the approval itself did nothing. The project stalled right before its key test.

**How to apply.** If any condition fails, use the normal path: decision task with a recommendation. If you recommend the free option and a paid alternative exists, do the free one and mention the paid one as a proposal. Narrowing an accepted decision (doing less, at no cost) is allowed; widening it is a new decision.
