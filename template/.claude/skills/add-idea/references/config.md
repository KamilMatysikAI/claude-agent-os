# add-idea configuration

Edit this file to fit your business. `/setup` or `/reflect` may propose changes; the skill only reads it.

## Categories

| Value | Use for |
|---|---|
| automation | bots, workflows, agents, scripts that save manual work |
| product | new products, features, offers |
| marketing | content, social media, ads, email |
| sales | pricing, partnerships, new customer segments, outreach |
| operations | processes, suppliers, finance, admin |
| new-venture | something entirely new: a new company or business line |
| other | everything else |

Replace or extend these with your own business lines. Keep values kebab-case.

## Category hints from the owner's words

| Words | Category |
|---|---|
| automate, bot, workflow, agent, script | automation |
| feature, product, offer, bundle | product |
| post, content, campaign, ad, newsletter | marketing |
| price, partner, wholesale, outreach, lead | sales |
| invoice, supplier, process, hiring | operations |
| new company, startup, side business | new-venture |

## Potential

| Value | Use for |
|---|---|
| high | large revenue or time saving, scalable |
| medium | noticeable effect, not game-changing |
| low | nice to have, small improvement |

Hints: "big", "huge", "this changes everything" → high; "small", "minor", "nice to have" → low.

## Effort

| Value | Use for |
|---|---|
| low | a few hours, no dependencies |
| medium | a few days, needs some planning |
| high | weeks, many dependencies |

## Suggested tags

`sales`, `marketing`, `automation`, `new-product`, `tech`, `cost-saving`, `customer`, `seo`, `social-media`, `ai`, `partnership`, `investment`, `email`, `ads`, `ux`, `content`, `lead-gen`, `b2b`, `b2c`

Pick 1–5 or add your own; stored as a YAML list: `tags: [ai, automation]`.

## Statuses (idea lifecycle)

| Status | Meaning |
|---|---|
| new | just added, not assessed |
| analysing | being assessed, data being gathered |
| approved | worth doing, waiting to start |
| in_progress | linked to a project or task (`project:` set) |
| done | implemented |
| rejected | a conscious decision not to do it (reason in the file) |

Ideas never move or get deleted; only `status` changes. `ideas/index.md` is regenerated from the files.
