# Optional · Web and CMS work

Enable this pack if agents build or edit websites for you. Numbered W1 to W4 so it does not clash with the core rules.

---

## W1. A page is verified in the render, on mobile too

**Rule.** After every change to a page, open it in a real browser, take a screenshot and check colors, spacing, links and anchors at desktop width and at 390 px. Code that looks right is not proof.

**Why.** Code can be correct while the page is broken: a cached stylesheet, a widget covering the button on a phone, an anchor that scrolls nowhere. Most end customers are on phones, so a desktop-only check misses what they actually see.

**How to apply.** Run `/design-audit` before reporting "works". Paste both screenshots or their paths into the task log as evidence.

## W2. CMS writes: backup, write, verify the front

**Rule.** Writing to a CMS through its API is never one step. (1) Back up the current content in edit context (non-empty raw content). (2) Write. (3) Fetch the public page anonymously with a cache-buster and compare content length with what you sent.

**Why.** Every skill that wrote through a REST API had its own code with no backup before writing and no way back. A "200 OK" response hid bot protection pages, silently dropped custom fields and truncated content.

**How to apply.** Check the HTTP status and the first bytes of the body before parsing JSON. Keep backups next to the task in `materials/` with a timestamp.

## W3. Ask first for the dangerous parts

**Rule.** Server-side code on production, plugins, global blocks and templates, menus, permanent deletes, slug changes without a redirect, and bulk edits of more than 5 pages need explicit approval.

**Why.** These are the changes that break many pages at once or cannot be undone from the API, and they are where an external maintainer's work is most likely to collide with yours.

**How to apply.** Prepare the change as a file plus description and a preview; wait for "go".

## W4. Every page ships with the basics

**Rule.** Favicon, alt texts, compressed modern image formats, unique titles and meta descriptions, Open Graph image, canonical tag, `robots.txt`, `sitemap.xml`, a custom 404, a real contact in the footer, and for forms or checkout: loading state, readable error messages, linked terms. A missing item means the page task is not done.

**Why.** The owner had to add these as separate instructions three times in five weeks (analytics, then SEO basics, then pre-launch basics), each time after a page shipped without them. A checklist in the definition of done ended the repeats.

**How to apply.** The `web` role lists the baseline. Tick it in `## Definition of done` of every page task.
