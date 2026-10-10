---
id: A-000
project: project-slug
title: Verb + concrete result
owner: copy                     # ceo|marketing|copy|web|soft|research
type: task                      # task|decision|review
status: todo                    # todo|in_progress|blocked|done|cancelled
priority: normal                # high|normal|low
due:
created: YYYY-MM-DD
closed:
size: medium                    # small|medium|large  (cut large into smaller tasks)
autonomy: full                  # full|ask   (ask = the queue skips it, a human runs it)
source: local                   # local|panel|external  (external = always the safe profile)
profile:                        # optional: safe|developer|full, never above the config maximum
blocked_by: []
unblocked_by:                   # REQUIRED when status is blocked: the H- task that unblocks
decision:
evidence:                       # REQUIRED to close: file path, link or test result
lock:
---

# Verb + concrete result

## Goal

<!-- What will exist when this is done. One sentence. -->

## Context

<!-- What the executor must know: inputs, where materials are, what not to touch.
If this task came from an instruction by the human, quote it here word for word. -->

## Steps

- [ ] step 1
- [ ] step 2

## Definition of done

<!-- Concrete and checkable. Names the evidence that will prove it:
a file path, a link, a screenshot, a test output. -->

## Unblocking action

<!-- Only when status is blocked: what exactly the human must do, pointing to unblocked_by. -->

## Owner notes

<!-- The human writes here. Agents read the LATEST note before acting or closing. -->

## Progress log

<!-- One line per step: - YYYY-MM-DD HH:MM — what was done, where the evidence is, what is next. -->
