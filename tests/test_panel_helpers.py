"""Fixture workspace for the panel tests (no tests in this file).

Used when `demo/` is missing or incomplete. Dates are relative to `today`, so the
fixture never goes stale.
"""

from __future__ import annotations

import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEMO = REPO / "demo"


def _task(root: Path, rel: str, meta: dict, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, list):
            value = "[" + ", ".join(value) + "]"
        lines.append(f"{key}: {value}".rstrip())
    lines.append("---")
    path.write_text("\n".join(lines) + "\n" + body.strip("\n") + "\n", encoding="utf-8")
    return path


def _meta(today: date, id_, project, title, owner, status="todo", type_="task", due=None,
          closed=None, priority="normal", evidence="", lock="", blocked_by=None,
          unblocked_by="", decision="", autonomy="full", created_days=6):
    return {
        "id": id_, "project": project, "title": title, "owner": owner, "type": type_,
        "status": status, "priority": priority,
        "due": (today + timedelta(days=due)).isoformat() if due is not None else "",
        "created": (today - timedelta(days=created_days)).isoformat(),
        "closed": (today + timedelta(days=closed)).isoformat() if closed is not None else "",
        "size": "small", "autonomy": autonomy, "source": "local", "profile": "",
        "blocked_by": blocked_by or [], "unblocked_by": unblocked_by, "decision": decision,
        "evidence": evidence, "lock": lock,
    }


def build_workspace(root: Path, today: date | None = None) -> Path:
    today = today or date.today()
    d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
    root.mkdir(parents=True, exist_ok=True)
    (root / "agentos.toml").write_text(
        'owner_name = "Alex"\nlanguage = "en"\n\n[panel]\nhost = "127.0.0.1"\nport = 8777\n',
        encoding="utf-8")
    (root / "inbox").mkdir(exist_ok=True)

    # ── project 1 ──
    p = root / "projects" / "coffee-shop"
    (p / "tasks").mkdir(parents=True, exist_ok=True)
    (p / "PROJECT.md").write_text(f"""---
slug: coffee-shop
name: Corner coffee shop launch
status: active
owner_human: Alex
wip_limit: 5
created: {d(-20)}
---

## Goal

Open the shop's online ordering and get the first 100 pickup orders.

## Success criteria

- 100 pickup orders through the site by {d(40)}.

## Constraints

- Budget for ads: set by the owner, agents never spend it.
""", encoding="utf-8")
    (p / "PLAN.md").write_text("""# Plan

## Phase 1: Foundations

- [x] Brand words and tone
- [x] Domain and hosting

## Phase 2: Website and menu (current)

- [x] Homepage copy
- [ ] Menu page
- [ ] Ordering form

## Phase 3: Launch week

- [ ] Launch offer
- [ ] Posts and newsletter
""", encoding="utf-8")
    (p / "LOG.md").write_text(f"""# Log

- {d(-6)} 10:12 — Project created, CEO planned three phases.
- {d(-3)} 16:40 — Homepage copy v1 shipped by copy.
- {d(-2)} 09:05 — Owner asked for a friendlier tone on the homepage.
- {d(-1)} 18:22 — Menu photos ready for review.
- {d(0)} 08:30 — Web started the menu page.
""", encoding="utf-8")
    T = p / "tasks"
    now_lock = datetime.now().isoformat(timespec="seconds") + "|demo-host|4242"
    _task(p, "tasks/H-001-pick-the-launch-offer.md",
          _meta(today, "H-001", "coffee-shop", "Pick the launch offer", "human",
                type_="decision", due=-1, priority="high"), f"""
## Goal

Choose the offer for launch week.

## Context

Two options were tested in a short survey of 40 regulars. See [survey notes](materials/survey.md).

## For approval

Accept **option B: 10% off the first pickup order**, valid for 7 days.

1. Survey: 26 of 40 picked B over a free pastry.
2. Cost is capped by the 7-day window.
3. Copy and posts can reuse one message.

## Progress log

- {d(-2)} 11:00 — CEO prepared the comparison.
""")
    _task(p, "tasks/H-002-approve-homepage-copy-v2.md",
          _meta(today, "H-002", "coffee-shop", "Approve homepage copy v2", "human",
                type_="decision", due=2), f"""
## Goal

Approve the friendlier homepage copy.

## For approval

Accept **v2** of the homepage copy (warmer tone, shorter hero, opening hours above the fold).

## Progress log

- {d(-1)} 17:10 — Copy delivered v2 after the owner note.
""")
    _task(p, "tasks/H-003-send-logo-files.md",
          _meta(today, "H-003", "coffee-shop", "Send the logo files to the web agent", "human",
                due=0, priority="high"), """
## Goal

Drop the SVG and PNG logo into `projects/coffee-shop/materials/`.

## Definition of done

Both files in the materials folder.
""")
    _task(p, "tasks/H-004-confirm-opening-hours.md",
          _meta(today, "H-004", "coffee-shop", "Confirm opening hours for the site", "human",
                due=-3), """
## Goal

Reply with the final weekday and weekend hours.
""")
    _task(p, "tasks/A-001-homepage-copy.md",
          _meta(today, "A-001", "coffee-shop", "Write homepage copy", "copy", status="done",
                closed=-3, evidence="projects/coffee-shop/materials/homepage-v1.md",
                created_days=10), f"""
## Goal

Homepage copy v1.

## Progress log

- {d(-3)} 16:40 — status in_progress -> done
""")
    _task(p, "tasks/A-002-build-the-menu-page.md",
          _meta(today, "A-002", "coffee-shop", "Build the menu page", "web",
                status="in_progress", due=1, lock=now_lock), f"""
## Goal

Menu page with prices from the menu file.

## Steps

- [x] Layout
- [ ] Prices from `materials/menu.csv`
- [ ] Mobile check at 390 px

## Progress log

- {d(0)} 08:30 — started
""")
    _task(p, "tasks/A-003-ordering-form.md",
          _meta(today, "A-003", "coffee-shop", "Ordering form with pickup time", "web",
                status="blocked", due=4, blocked_by=["A-002"], unblocked_by="H-003"), """
## Goal

Pickup order form.

## Unblocking action

Send the logo files (H-003) so the form header can be finished.
""")
    _task(p, "tasks/A-004-launch-week-posts.md",
          _meta(today, "A-004", "coffee-shop", "Plan launch week posts", "marketing",
                due=6, blocked_by=["A-003"]), """
## Goal

Seven posts for launch week.
""")
    _task(p, "tasks/A-005-review-menu-photos.md",
          _meta(today, "A-005", "coffee-shop", "Review the menu photos", "human",
                type_="review", due=1), """
## Goal

Pick 6 of the 14 photos for the menu page.

## Context

Photos are in `materials/photos/`. Agent shortlist: 2, 3, 5, 8, 11, 14.
""")
    _task(p, "tasks/A-006-competitor-prices.md",
          _meta(today, "A-006", "coffee-shop", "Compare prices of 5 nearby cafes", "research",
                status="done", closed=0, evidence="projects/coffee-shop/materials/prices.md"),
          f"""
## Progress log

- {d(0)} 07:55 — status in_progress -> done
""")
    _task(p, "tasks/A-007-newsletter-signup.md",
          _meta(today, "A-007", "coffee-shop", "Add a newsletter signup box", "web",
                status="cancelled", closed=0), f"""
## Progress log

- {d(0)} 00:01 — status todo -> cancelled: owner moved it to the newsletter project
""")
    _task(p, "tasks/A-008-seo-basics.md",
          _meta(today, "A-008", "coffee-shop", "SEO basics: titles, sitemap, robots", "web",
                due=8, priority="low"), "## Goal\n\nBasics before launch.\n")
    _task(p, "tasks/A-009-ask-mode.md",
          _meta(today, "A-009", "coffee-shop", "Rewrite the about page", "copy",
                autonomy="ask", due=9), "## Goal\n\nNeeds a talk with the owner first.\n")
    _task(p, "tasks/archive/A-000-old-archived.md",
          _meta(today, "A-010", "coffee-shop", "Old archived task", "copy", status="done",
                closed=-40, evidence="old"), "## Goal\n\nArchived.\n")

    # ── project 2 ──
    q = root / "projects" / "newsletter"
    (q / "tasks").mkdir(parents=True, exist_ok=True)
    (q / "PROJECT.md").write_text(f"""---
slug: newsletter
name: Weekly newsletter
status: active
owner_human: Alex
wip_limit: 3
created: {d(-12)}
---

## Goal

A weekly email that brings regulars back.

## Success criteria

- 300 subscribers and 40% open rate by {d(60)}.
""", encoding="utf-8")
    (q / "LOG.md").write_text(f"- {d(-1)} 20:00 — Issue #1 draft ready.\n", encoding="utf-8")
    _task(q, "tasks/H-001-choose-send-day.md",
          _meta(today, "H-001", "newsletter", "Choose the send day", "human",
                type_="decision", due=3), """
## For approval

Send on **Thursday 7:00**, so the weekend offer lands before plans are made.
""")
    _task(q, "tasks/H-002-import-contacts.md",
          _meta(today, "H-002", "newsletter", "Export contacts from the old tool", "human",
                due=4), "## Goal\n\nCSV export, consent column included.\n")
    _task(q, "tasks/A-001-issue-one.md",
          _meta(today, "A-001", "newsletter", "Draft issue #1", "copy", status="done",
                closed=-1, evidence="projects/newsletter/materials/issue-1.md"),
          f"## Progress log\n\n- {d(-1)} 20:00 — status in_progress -> done\n")
    _task(q, "tasks/A-002-welcome-sequence.md",
          _meta(today, "A-002", "newsletter", "Welcome email sequence", "copy", due=5,
                blocked_by=["H-002"]), "## Goal\n\nThree welcome emails.\n")

    # ── inbox ──
    _task(root, "inbox/check-broken-links.md",
          _meta(today, "", "", "Check the site for broken links", "web", due=2),
          "## Goal\n\nReport only.\n")
    return root


def workspace_copy(tmp_path: Path) -> Path:
    """Fresh workspace: a copy of demo/ when it is a complete workspace, else the fixture."""
    target = tmp_path / "ws"
    if (DEMO / "agentos.toml").is_file() and (DEMO / "projects").is_dir():
        shutil.copytree(DEMO, target, ignore=shutil.ignore_patterns(".agentos"))
        return target
    return build_workspace(target)
