# CONTEXT · the business

<!--
The facts every agent needs so you never have to explain them twice.
/setup fills this with you; /reflect and memory-update keep it current.
Rule of thumb: put stable facts here. Fast-changing numbers (balances, stock, statuses)
belong in their source system; agents must read them there (rule 3).
Delete these comments when done.
-->

## What the business is

<!--
One line per business or project: what it sells, to whom, at what stage.
-->

## How it makes money

| Stream | Model | State |
|---|---|---|
| <!-- e.g. online shop --> | <!-- B2C, subscriptions --> | <!-- stable / growing / paused --> |

## Customers

<!--
For each segment: who they are, why they buy, why they don't.
-->

## Tools and accounts

<!--
Where the data lives. Agents read data from these, never from memory.
- Shop / CMS:
- Email tool:
- Ads:
- Accounting / invoicing:
- Code repositories:
Never put keys or passwords here. Secrets go in .env only (rule 12).
-->

## Standing approvals

<!--
What agents may do without asking. Example:
- Deploy internal tools after green tests, with verification and a report (rule 22).
Always excluded: irreversible operations, spending money, mass sends, publishing in my name.
-->

## Systems with an outside maintainer

<!--
Read freely, change only after an explicit "go" (rule 15). Example:
- The shop front-end (maintained by an external developer).
-->

## People and channels

<!--
Who else is involved, by role, and how agents reach them.
e.g. "Sales team: questions go by email draft, not through me."
-->
