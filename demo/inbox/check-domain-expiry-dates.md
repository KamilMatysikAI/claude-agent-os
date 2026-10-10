---
id:
project:
title: List the expiry dates of all business domains
owner: research
type: task
status: todo
priority: normal
due: 2026-10-16
created: 2026-10-10
closed:
size: small
autonomy: full
source: panel
profile:
blocked_by: []
unblocked_by:
decision:
evidence:
lock:
---

# List the expiry dates of all business domains

## Goal

One table with every domain the business owns, its registrar and its expiry date, so none lapses by accident.

## Context

Submitted from the panel by Alex: "Check when our domains expire, I think one is close."
Domain list is in `.claude/rules/context.md`, section "Tools and accounts". Use public WHOIS/RDAP lookups only; do not log in to any registrar.

## Steps

- [ ] Read the domain list from context.md
- [ ] Look up each domain's expiry date through public RDAP
- [ ] Table sorted by expiry date; flag anything expiring within 60 days
- [ ] For each flagged domain, create a human task "renew domain X" with the registrar link as the first step

## Definition of done

Table saved as `inbox/done/domain-expiry-YYYY-MM-DD.md`; human tasks created for domains expiring within 60 days.

## Owner notes

## Progress log
