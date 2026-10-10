---
id: H-000
project: project-slug
title: "Decision: one concrete question"
owner: human
type: decision
status: todo
priority: normal
due:
created: YYYY-MM-DD
closed:
size: small
autonomy: ask
source: local
profile:
blocked_by: []
unblocked_by:
decision:                       # accepted|rejected, set when the human decides
evidence:
lock:
---

# Decision: one concrete question

## For approval

<!-- The recommendation the human accepts or rejects, in 1 to 3 sentences:
WHAT happens after acceptance, what it COSTS (money, time, risk), and the alternative rejected.
The human should decide in 30 seconds without opening another file.

Example: "Recommend: buy the domain example-shop.com for about 12 per year on the company card.
After acceptance web registers it and points it at the landing page within 2 days.
Rejected: the .net variant (cheaper but already used by a competitor)." -->

## Context

<!-- Optional, at most 5 lines: where the proposal came from, what was considered. -->

## Owner notes

<!-- The human's comment on the decision. It can change the terms
("yes, but the cheaper option"). The executing task must read it. -->

## Progress log

- YYYY-MM-DD HH:MM — Decision task created by <role>.

<!--
RULES FOR THE AGENT CREATING THIS TASK
1. One task = one decision. Four questions = four tasks. Easy questions get answered,
   hard ones on a list disappear.
2. Always a ready recommendation (yes/no or A over B) with its cost. Never "what do you think?".
3. Before creating: look it up (memory, LOG.md, configs). Zero-cost, reversible, with a precedent?
   Then it is not a decision: do it and log it (rule 8).
4. Tasks waiting for this decision: status blocked, blocked_by: [<this id>].
   After acceptance the guard creates the executing A- task if none exists.
-->
