---
id: A-006
project: coffee-shop
title: Connect the subscription checkout to the payment provider
owner: soft
type: task
status: blocked
priority: high
due: 2026-10-24
created: 2026-09-22
closed:
size: medium
autonomy: full
source: local
profile: developer
blocked_by: [H-005, H-002]
unblocked_by: H-005
decision:
evidence:
lock:
---

# Connect the subscription checkout to the payment provider

## Goal

The subscribe button on the landing page leads to a working monthly checkout at 24 EUR, tested end to end in test mode.

## Context

Price from H-002. Shop platform's built-in subscription feature (delegated decision 2026-09-23 in PLAN.md). API keys go into `.env` only, never into the task or the code.

## Steps

- [ ] Add the provider's test keys to `.env` (after H-005)
- [ ] Create the monthly plan at 24 EUR
- [ ] Wire the button from A-004 to the plan
- [ ] Test orders in test mode: success, card declined, cancel
- [ ] Second pair of eyes: review by a different model or by Alex (payments, rule 14)

## Definition of done

Three test-mode orders with expected results, logged with their order IDs; review recorded in the log.

## Unblocking action

Alex opens the payment account and submits verification: H-005, 15 minutes, answers already prepared.

## Owner notes

## Progress log

- 2026-09-22 15:31 — Blocked on H-005 from the start; steps prepared so work can begin the day the account exists.
