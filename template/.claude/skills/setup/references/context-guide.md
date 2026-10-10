# How to write context.md

context.md is the single source of business facts every agent reads. Persona describes the person; context describes the business. If the workspace template has headings, keep them.

```markdown
# CONTEXT — business facts

## 1. What the business does
<company or projects, industry, model, rough scale; one short block per business line>

## 2. Customers
| Line | Who buys / uses it |
|---|---|

## 3. Channels
<where you sell, where you market, where customers reach you>

## 4. Stack
<tools and platforms, grouped: sales, marketing, automation, hosting, AI>

## 5. Systems maintained by someone else
<systems with an outside maintainer: read-only for agents; any change is a decision task for the owner>

## 6. Current projects
<one line each; details live in projects/<slug>/PROJECT.md>

*Last edit: YYYY-MM-DD*
```

## Rules

1. **Facts only**, from the owner's answers. No marketing language.
2. **Mark uncertain facts** with "(to confirm)" instead of guessing.
3. **Volatile numbers** (balances, prices, stock, status) do not belong here. They change faster than this file; agents must check them at the source.
4. **Short.** 40–120 lines. Detail goes into project files.
5. **Date every correction** at the bottom so a later reader knows which version is newer.
