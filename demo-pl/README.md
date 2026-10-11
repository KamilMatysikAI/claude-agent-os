# Demo workspace in Polish

A fictional owner ("Ola") with eight small businesses, used for the Polish panel screenshots
and the tests. All names, prices and numbers are invented. Dates are fixed around 2026-10-11.
The installer copies this demo instead of `demo/` when the language is Polish:

```bash
python install.py --non-interactive --workspace ~/agentos-demo-pl --language pl --with-demo --no-queue --no-schedule
```

Content is Polish; file names, frontmatter fields and section names (`## Goal`,
`## Progress log`) stay English, because they are the file contract the engine reads. The panel
shows the section names translated.

| Project | Name in the panel |
|---|---|
| `kawiarnia-subskrypcja` | Kawiarnia z subskrypcją kawy (coffee subscription) |
| `podcast-piwo` | Podcast o piwie domowym (home-brewing podcast) |
| `sklep-ceramika` | Sklep z ceramiką (ceramics shop) |
| `osiedle-12-domow` | Osiedle 12 domów (12 houses, pre-sales) |
| `wynajem-kawalerek` | Wynajem kawalerek (studio flats for rent) |
| `kurs-online` | Kurs online z fotografii mobilnej (online course) |
| `newsletter-lokalny` | Newsletter lokalny (local newsletter) |
| `automatyzacje-biura` | Automatyzacje biura (office automations) |
| `inbox/` | two ad-hoc tasks, one `source: external` with a forwarded email asking for a login |

At a glance: 85 tasks, 62 open (60 in projects), 8 open decisions (one overdue), 22 tasks for
Ola (decisions included), 6 blocked agent tasks, 15 tasks in progress. The Tree screen shows all eight projects with
six agent roles and Ola.

The demo is a fixed point for the guard: `guard` on a fresh copy changes nothing.
