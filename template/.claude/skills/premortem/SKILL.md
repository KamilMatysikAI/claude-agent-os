---
name: premortem
description: Forced risk analysis of a project or decision using the premortem technique. Instead of asking "what could go wrong" (cautious, generic answers), it assumes the plan HAS ALREADY FAILED N months from now and explains backwards why — the narrative frame forces concrete mechanisms. Works on a project in projects/<slug>/ (reads PROJECT.md, PLAN.md, LOG.md) or on any pasted plan or decision. Use for "premortem", "/premortem <slug>", "what could kill this", "stress-test this plan", "tear this plan apart", "assume this failed".
argument-hint: "<project slug> | <pasted plan or decision> [N months]"
allowed-tools: ["Read", "Write", "Glob", "Grep", "Agent"]
---

# /premortem — the plan already failed; explain why

"What could go wrong?" produces defensive, generic lists ("the market may change", "costs may rise"). A premortem flips the frame: **the plan has already failed, at a specific point in the future, and you must explain it backwards** — like an incident report, not a lawyer's list of caveats. The narrative mode makes people (and models) look for mechanisms instead of generalities.

## 0. Input and mode

| Input | Mode |
|---|---|
| A slug that exists in `projects/<slug>/` | **project** — context from the project files |
| A pasted plan or decision, no slug | **ad-hoc** — context only from what the owner gave |
| A name matching no project | Glob `projects/*/PROJECT.md`; if there is still no match, ask whether it is a new project (too little context) or ad-hoc |

Do not guess missing context. In ad-hoc mode, if the **goal** and the **success criterion** (what "it worked" means) are missing, ask for them first. Without them there is nothing for "failure" to be measured against.

## 1. Gather context

**Project mode:**
- `projects/<slug>/PROJECT.md` — goal, success criteria, constraints, out of scope, dates.
- `projects/<slug>/PLAN.md` — phases, their state, any "Risks" section. That list is **input**, not a substitute: the premortem must also find causes not on it.
- `projects/<slug>/LOG.md` — the latest 2–3 entries, for recent turns.
- Glob `projects/<slug>/tasks/*.md` — a quick picture of what is todo / in progress / blocked, without reading every file.

**Ad-hoc mode:** the owner's text is the only source.

Write a **plan summary** of 3–6 sentences: what we do, why, how success is measured, which constraints are known. It goes into the report and into every subagent prompt in step 4.

## 2. The frame: it failed N months from now

Set N (months):
1. If the owner gave N, use it.
2. If the project has a date in PROJECT.md, N is the distance from today to the moment the **result** would be visible, not just the decision date. A go/no-go decision is not yet a success or a failure; add the typical time to execute.
3. No date at all → **12 months**, stated in the report ("N was not set; I used 12 months").

The frame, for your own use:

> It is <today + N months>. <Project/decision> turned out to be a failure: not a hypothesis, a fact we now know. Nobody asks "what could have gone wrong"; they ask "what went wrong". Reconstruct it backwards: who made which decision, which signal was ignored, which number in the model was off, what changed in the market or with a counterparty, what was not checked in time.

Hard rule: reasons are written **in the past tense, as a narrative, with specifics**. Not "costs may rise" but "the fit-out cost exceeded estimate v1 by a third because the contractor priced materials after the spring increase and we used last year's prices". If it comes out generic, it is not finished; dig further.

## 3. 3–7 concrete reasons for failure

Different reasons from different categories, so you do not get seven variants of one risk:

| Category | Helper question |
|---|---|
| Model / numbers | Which numeric assumption (price, cost, demand, margin) was wrong, and why did we miss exactly that one? |
| External / market / counterparty | What did someone outside our control (supplier, buyer, authority, competitor, partner) do that we did not expect? |
| Execution / operations | What went slower, more expensive or worse than planned even though the decision was right? |
| People / decisions | Which decision during the project, made under time pressure or fatigue, turned out wrong? |
| Law / regulation | What changed formally (a rule, a requirement, an interpretation) and why did we not react in time? |
| Timing / competition | Did someone else settle the matter before we could act? |
| Hidden assumption | What does the plan rest on so obviously that nobody wrote it down — and what if it was false? |

You do not need all seven. 3–7 real, different reasons beat a complete table. Treat risks already listed in PLAN.md as a starting point, do not copy them 1:1. The value is in mechanisms not yet on the list, e.g. two known risks that look harmless alone but combine.

## 4. Analyse each reason in parallel

Large, multi-threaded work → a fan of parallel subagents instead of a sequential pass. For each reason, launch **one** agent with the Agent tool, all in a single message (in parallel). Use `subagent_type: research` by default (it checks external realities: market, rules, precedents); for purely execution or technical reasons use `general-purpose`.

Prompt for each agent (self-contained, no memory of this conversation):

```
You are analysing ONE failure scenario of the project "<name>" (context: <plan summary from step 1>).
Scenario:

"<the narrative reason from step 3, full text>"

Do NOT judge whether the project is good. Judge THIS scenario:
1. Probability (low / medium / high) + 1–2 sentences of justification based on facts in the context, not on a hunch.
2. Early warning signals: 2–4 concrete, observable things that would show up BEFORE the scenario happens (not after).
3. Cost if it happens: financial (amount or order of magnitude), time (delay), reputational or relational if relevant. Concrete, not "a big cost".
4. One preventive recommendation: the cheapest move that lowers the probability or the cost.

Answer in under 200 words, in <language from agentos.toml>. If the context lacks data for a number, say so instead of guessing.
```

If spawning several agents makes no sense (a demo, a quick pass, no Agent tool), do the same analysis yourself, reason by reason, with the same four questions and the same bar for specifics. The mechanism differs, the quality and structure must not.

## 5. Synthesis (you, not a subagent)

- **Most likely failure** — the reason with the highest probability; on a tie, the one with weaker or less controllable early signals.
- **Most dangerous failure** — the highest cost, EVEN IF its probability is low. Unlikely catastrophes disappear in averaged risk scores; the premortem must surface them.
- **Hidden assumption** — one sentence: what the whole plan rests on that nobody wrote down in PROJECT.md or PLAN.md. It usually comes from where 2–3 reasons intersect.
- **Revised plan** — 2–5 concrete changes (not "be careful about X") to consider for PLAN.md / PROJECT.md. The premortem **proposes**; it does not edit those files. The plan belongs to the `ceo` role (or the owner in ad-hoc mode).
- **Pre-start checklist** — 3–6 checkboxes, each doable and verifiable (not "think about the risk", but e.g. "get a binding quote from the contractor before setting the final price").

## 6. Save the result

- **Project mode** → `projects/<slug>/materials/premortem-YYYY-MM-DD.md`
- **Ad-hoc mode** → `notes/premortem-YYYY-MM-DD-<topic-slug>.md` (create `notes/` if missing)

If the file already exists (second run on the same day), **do not overwrite**: add the time to the name (`premortem-YYYY-MM-DD-HHMM.md`).

```markdown
---
project: <slug or "ad-hoc">
date: YYYY-MM-DD
horizon_months: <N>
reference_date: <today + N months>
---

# Premortem — <project / decision name>

## Plan summary (as of today)
<3–6 sentences from step 1>

## Frame
It is <today + N months>. <Name> failed. Below, the reconstruction backwards: why.

## Reasons for failure

### 1. <Title> (category: <...>)
<3–5 sentence narrative, past tense, specific>

- **Probability:** low / medium / high — <justification>
- **Early signals:** <list>
- **Cost if it happens:** <specific>
- **Prevention:** <one move>

<... 3–7 reasons in total ...>

## Synthesis
**Most likely failure:** <reason> — <why>
**Most dangerous failure (even if unlikely):** <reason> — <why>
**Hidden assumption the plan rests on:** <one sentence>
**Revised plan — what to add or change:**
1. <specific>
2. <specific>

## Pre-start checklist
- [ ] <specific, verifiable>
- [ ] <specific, verifiable>
```

After saving, tell the owner briefly (not the whole file): the path, the most likely and the most dangerous reason, the hidden assumption, and one sentence on whether any item should go into PLAN.md. If yes, offer to create a task for the `ceo` with `create-task`.

## When to use

- Before the first PLAN.md of a new project is approved (the `ceo` can call it as a step).
- Before a high-stakes, irreversible or expensive-to-undo decision: a large purchase, a launch go/no-go, a big price change, a new key partner.
- Any time the owner wants to "stress-test the plan". No need to wait for a formal moment.

## Constraints

- **The frame is always "it already failed", never "what could go wrong".** The conditional question produces generalities; that is the whole point of the technique.
- **Narrative, not keywords.** Each reason is 3–5 sentences with specifics (numbers, roles, the mechanism), not "market risk".
- **Read-only on PROJECT.md / PLAN.md / LOG.md.** The premortem reads and proposes.
- **Real data from the project, no invented numbers.** When data for a cost or probability is missing, say it is missing.
- **Nothing is deleted or overwritten.** A repeated run gets a new file.
- **Analysis is free; action is not.** Checklist items do not authorise changes to systems that need the owner's approval.
