"""Read side of the panel: scans the workspace through `agentos.core` and builds the
JSON payloads for the four screens (Today, Decisions, Projects, Activity), the
organisation tree (owner -> projects -> roles -> tasks), the per-project dependency
tree and the task detail.

Rules that shaped this module:
- Payloads carry open tasks plus the last 7 days. The full archive is sent only when
  the client asks for it (`scope=all`, `archive=1`). Sending every closed task on every
  refresh made a panel with a few thousand files take 10+ seconds to open.
- Tasks are addressed by a KEY (`<project>/<ID>` or `inbox/<file-stem>`), never by a
  path. A key is resolved by looking it up in the scanned index, so a request can never
  name a file outside the task directories.
- One unreadable file never breaks a screen: it is skipped and listed in `errors`.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from agentos import core

RECENT_DAYS = 7
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,80}$")
ID_RE = re.compile(r"^[A-Z]-\d{1,6}$")
STEM_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,160}$")
STAMP_RE = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
INBOX = "inbox"


def valid_key(key: str) -> bool:
    parts = (key or "").split("/")
    if len(parts) != 2:
        return False
    scope, ident = parts
    if scope == INBOX:
        return bool(STEM_RE.match(ident))
    return bool(SLUG_RE.match(scope)) and bool(ID_RE.match(ident))


@dataclass
class Entry:
    task: core.Task
    key: str
    archived: bool
    mtime: float


class Workspace:
    """Scanned view of one workspace. Parsing is cached by (mtime_ns, size), so a
    refresh only re-reads files that changed."""

    def __init__(self, root: str | os.PathLike, cfg: dict | None = None):
        self.root = Path(root).resolve()
        self.cfg = cfg if cfg is not None else core.load_config(self.root)
        self._cache: dict[Path, tuple[int, int, core.Task]] = {}
        self._lock = threading.Lock()
        self.errors: list[str] = []
        self.hidden_keys: set[str] = set()   # keys with a pending (undoable) action

    # ── time ──────────────────────────────────────────────────────────────────
    def now(self) -> datetime:
        return core.now_local(self.cfg)

    def today(self) -> date:
        return self.now().date()

    # ── scanning ──────────────────────────────────────────────────────────────
    def _read_cached(self, path: Path, errors: list) -> core.Task | None:
        try:
            st = path.stat()
        except OSError as exc:
            errors.append(f"{self.rel(path)}: {exc.strerror or exc}")
            return None
        hit = self._cache.get(path)
        if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            return hit[2]
        try:
            task = core.read_task(path)
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{self.rel(path)}: {exc}")
            return None
        self._cache[path] = (st.st_mtime_ns, st.st_size, task)
        return task

    def _sources(self):
        for pdir in core.iter_project_dirs(self.root):
            tdir = pdir / "tasks"
            if tdir.is_dir():
                yield pdir.name, tdir
        inbox = self.root / INBOX
        if inbox.is_dir():
            yield "", inbox

    def scan(self) -> list[Entry]:
        errors: list[str] = []
        entries: dict[str, Entry] = {}
        seen: set[Path] = set()
        with self._lock:
            for slug, tdir in self._sources():
                for path in sorted(tdir.rglob("*.md")):
                    if path.name.startswith(".") or any(p.startswith(".") for p in
                                                        path.relative_to(tdir).parts[:-1]):
                        continue
                    seen.add(path)
                    task = self._read_cached(path, errors)
                    if task is None:
                        continue
                    if "status" not in task.meta and "id" not in task.meta:
                        continue
                    if slug and not task.project:
                        task.meta["project"] = slug
                    archived = path.parent != tdir
                    if slug:
                        if not ID_RE.match(task.id):
                            errors.append(f"{self.rel(path)}: missing or invalid id")
                            continue
                        key = f"{slug}/{task.id}"
                    else:
                        stem = core.slugify(path.stem, max_len=160)
                        key = f"{INBOX}/{stem}"
                    try:
                        mtime = path.stat().st_mtime
                    except OSError:
                        mtime = 0.0
                    entry = Entry(task, key, archived, mtime)
                    old = entries.get(key)
                    if old is not None:
                        # duplicate key: the live file wins over an archived copy
                        errors.append(f"{self.rel(path)}: duplicate {key}")
                        if old.archived and not archived:
                            entries[key] = entry
                        continue
                    entries[key] = entry
            for stale in [p for p in self._cache if p not in seen]:
                self._cache.pop(stale, None)
        self.errors = errors
        return list(entries.values())

    def index(self) -> dict[str, Entry]:
        return {e.key: e for e in self.scan()}

    def find(self, key: str) -> Entry | None:
        if not valid_key(key):
            return None
        return self.index().get(key)

    def rel(self, path: Path) -> str:
        try:
            return Path(path).resolve().relative_to(self.root).as_posix()
        except ValueError:
            return Path(path).name

    # ── projects ──────────────────────────────────────────────────────────────
    def projects(self) -> dict[str, dict]:
        out = {}
        for pdir in core.iter_project_dirs(self.root):
            if not SLUG_RE.match(pdir.name):
                continue
            proj = core.read_project(pdir)
            meta = proj.meta if proj else {}
            out[pdir.name] = {
                "slug": pdir.name,
                "name": str(meta.get("name") or pdir.name),
                "status": str(meta.get("status") or "active").lower(),
                "wip_limit": _int(meta.get("wip_limit"),
                                  self.cfg.get("projects", {}).get("wip_limit", 5)),
                "dir": pdir,
                "doc": proj,
            }
        return out


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ── serialization ─────────────────────────────────────────────────────────────

def _is_open(task: core.Task) -> bool:
    return task.status in core.OPEN_STATUSES


def _closed_date(entry: Entry) -> date | None:
    d = core.parse_date(entry.task.get("closed"))
    if d:
        return d
    if entry.task.status in core.CLOSED_STATUSES:
        return datetime.fromtimestamp(entry.mtime).date() if entry.mtime else None
    return None


def last_stamp(text: str) -> datetime | None:
    """Latest `YYYY-MM-DD[ HH:MM]` stamp at the start of a bullet line."""
    best = None
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith(("-", "*")):
            continue
        m = STAMP_RE.search(line[:24])
        if not m:
            continue
        try:
            moment = datetime.fromisoformat(m.group(1) + (" " + m.group(2) if m.group(2) else ""))
        except ValueError:
            continue
        if best is None or moment > best:
            best = moment
    return best


def _event_time(entry: Entry) -> datetime:
    """When the task was last touched: progress log stamp, closed date or mtime."""
    stamp = last_stamp(entry.task.section("Progress log"))
    closed = _closed_date(entry)
    if stamp and (not closed or stamp.date() >= closed):
        return stamp
    if closed:
        mt = datetime.fromtimestamp(entry.mtime) if entry.mtime else None
        if mt and mt.date() == closed:
            return mt
        return datetime.combine(closed, datetime.min.time()).replace(hour=12)
    return datetime.fromtimestamp(entry.mtime) if entry.mtime else datetime.min


def _recorded_time(entry: Entry) -> datetime | None:
    """Time written INTO the file (progress log stamp or closed date). File mtimes lie
    after a copy, a sync or a checkout, so they are not used for "last move"."""
    stamp = last_stamp(entry.task.section("Progress log"))
    closed = core.parse_date(entry.task.get("closed"))
    if stamp and (not closed or stamp.date() >= closed):
        return stamp
    if closed:
        return datetime.combine(closed, datetime.min.time())
    return None


def _last_move(entries: list[Entry], project_dir: Path) -> tuple[Entry | None, datetime | None]:
    best, when = None, None
    for e in entries:
        t = _recorded_time(e)
        if t and (when is None or t > when):
            best, when = e, t
    log = _log_entries(_read_text(project_dir / "LOG.md"), limit=1)
    if log and log[0]["when"]:
        try:
            lt = datetime.fromisoformat(log[0]["when"])
        except ValueError:
            lt = None
        if lt and (when is None or lt > when):
            when = lt
            best = None if not best or _recorded_time(best) != lt else best
    return best, when


def run_now_block(entry: Entry) -> tuple[str, dict, str]:
    """Why the queue would NOT take this task, as (code, params, English text); all
    empty when it would. Mirrors the runner's own rules, so the panel never pretends a
    run started when it cannot. The code is translated by the panel (`srv.<code>`)."""
    t = entry.task
    if entry.archived:
        return ("run_archived", {},
                "This task is archived. Move it back to the tasks folder to run it.")
    if t.is_human:
        return "run_human", {}, "This is your task. The queue only runs agent tasks."
    if t.s("type") == "decision":
        return "run_decision", {}, "Decisions are made by you, not by the queue."
    if t.s("autonomy") == "ask":
        return ("run_ask", {},
                "This task has autonomy: ask. Run it from an interactive session instead.")
    if t.status != "todo":
        return ("run_not_waiting", {"state": t.status},
                f"Only waiting tasks (status: todo) can be started; this one is {t.status}.")
    if core.lock_alive(str(t.get("lock"))):
        return "run_locked", {}, "An agent is already working on this task."
    return "", {}, ""


def run_now_block_reason(entry: Entry) -> str:
    """English reason only (empty string = the queue would take it)."""
    return run_now_block(entry)[2]


def summary(entry: Entry, ws: Workspace, projects: dict, unblocks: dict | None = None) -> dict:
    t = entry.task
    today = ws.today()
    due = core.parse_date(t.get("due"))
    overdue = (today - due).days if (due and _is_open(t) and due < today) else 0
    proj = projects.get(t.project, {})
    closed = _closed_date(entry)
    return {
        "key": entry.key,
        "id": t.id,
        "project": t.project,
        "project_name": proj.get("name", t.project or "Inbox"),
        "title": t.title,
        "owner": t.owner or ("human" if t.is_human else ""),
        "human": t.is_human,
        "type": t.s("type") or "task",
        "status": t.status,
        "priority": t.s("priority") or "normal",
        "due": due.isoformat() if due else "",
        "overdue_days": overdue,
        "closed": closed.isoformat() if closed and not _is_open(t) else "",
        "archived": entry.archived,
        "blocked_by": t.list("blocked_by"),
        "unblocked_by": str(t.get("unblocked_by") or "").strip(),
        "decision": t.s("decision"),
        "evidence": str(t.get("evidence") or "").strip(),
        "working": core.lock_alive(str(t.get("lock"))),
        "autonomy": t.s("autonomy") or "full",
        "size": t.s("size"),
        "unblocks": (unblocks or {}).get(entry.key, 0) if _is_open(t) else 0,
    }


def _unblock_counts(entries: list[Entry]) -> dict[str, int]:
    """key -> number of OPEN tasks in the same project waiting on it."""
    counts: dict[str, int] = {}
    for e in entries:
        t = e.task
        if not _is_open(t) or not t.project:
            continue
        refs = set(t.list("blocked_by"))
        ub = str(t.get("unblocked_by") or "").strip()
        if ub:
            refs.add(ub)
        for ref in refs:
            if ID_RE.match(ref):
                k = f"{t.project}/{ref}"
                counts[k] = counts.get(k, 0) + 1
    return counts


def _visible(entries: list[Entry], ws: Workspace) -> list[Entry]:
    return [e for e in entries if e.key not in ws.hidden_keys]


def _recent(entry: Entry, ws: Workspace, days: int = RECENT_DAYS) -> bool:
    if _is_open(entry.task):
        return not entry.archived
    closed = _closed_date(entry)
    return bool(closed and closed >= ws.today() - timedelta(days=days))


def _due_key(s: dict):
    return (s["due"] or "9999-99-99", core.PRIORITY_RANK.get(s["priority"], 1), s["key"])


def recommendation(task: core.Task) -> str:
    return task.section("For approval")


# ── payloads ──────────────────────────────────────────────────────────────────

PANEL_LANGUAGES = ("en", "pl")


def panel_language(value) -> str:
    """Panel UI language from `language` in agentos.toml ("pl", "pl-PL", "Polish" -> pl).
    Anything without a panel dictionary falls back to English."""
    v = str(value or "").strip().lower().replace("_", "-")
    if v.startswith("pl") or v in ("polski", "polish"):
        return "pl"
    return "en"


def meta_payload(ws: Workspace) -> dict:
    import agentos
    from agentos import updates
    now = ws.now()
    return {
        "product": getattr(agentos, "PRODUCT_NAME", "agentos"),
        "version": getattr(agentos, "__version__", ""),
        "owner_name": str(ws.cfg.get("owner_name") or "Owner"),
        "language": panel_language(ws.cfg.get("language")),
        "languages": list(PANEL_LANGUAGES),
        "today": now.date().isoformat(),
        "now": now.isoformat(timespec="minutes"),
        "config_error": ws.cfg.get("_error", ""),
        "update": updates.status(ws.root, ws.cfg),
    }


def decisions_payload(ws: Workspace, full: bool = True) -> dict:
    entries = _visible(ws.scan(), ws)
    projects = ws.projects()
    out = []
    for e in entries:
        t = e.task
        if e.archived or not _is_open(t) or t.s("type") != "decision":
            continue
        s = summary(e, ws, projects)
        rec = recommendation(t)
        s["recommendation"] = rec if full else rec[:280]
        if full:
            s["context"] = t.section("Context")
            s["goal"] = t.section("Goal")
            s["notes"] = t.section("Owner notes")
            s["links"] = [{"label": m.group(1), "href": m.group(2)}
                          for m in LINK_RE.finditer(t.body)][:12]
        out.append(s)
    out.sort(key=lambda s: (0 if s["overdue_days"] else 1, _due_key(s)))
    overdue = sum(1 for s in out if s["overdue_days"])
    return {"items": out, "count": len(out), "overdue": overdue,
            "on_time": len(out) - overdue}


def today_payload(ws: Workspace) -> dict:
    entries = _visible(ws.scan(), ws)
    projects = ws.projects()
    counts = _unblock_counts(entries)
    today = ws.today()
    week = today + timedelta(days=7)
    mine_today, overdue, this_week, later = [], [], [], []
    review, waiting = [], []
    by_key = {e.key: e for e in entries}
    for e in entries:
        t = e.task
        if e.archived or not _is_open(t):
            continue
        s = summary(e, ws, projects, counts)
        typ = s["type"]
        if typ == "review":
            review.append(s)
        elif t.is_human and typ != "decision":
            due = core.parse_date(t.get("due"))
            if due and due < today:
                overdue.append(s)
            elif due and due == today:
                mine_today.append(s)
            elif due and due <= week:
                this_week.append(s)
            else:
                later.append(s)
        if (not t.is_human and t.status == "blocked"):
            ub = s["unblocked_by"]
            hk = f"{t.project}/{ub}" if (t.project and ub) else ""
            human_task = by_key.get(hk)
            if human_task is None or human_task.task.is_human:
                s["unblocking_action"] = t.section("Unblocking action")
                s["unblocked_by_key"] = hk if human_task else ""
                waiting.append(s)

    def mine_sort(s):
        return (-s["unblocks"],) + _due_key(s)

    for group in (mine_today, overdue, this_week, later):
        group.sort(key=mine_sort)
    review.sort(key=_due_key)
    waiting.sort(key=_due_key)
    dec = decisions_payload(ws, full=False)
    agents_working = sum(1 for e in entries if not e.archived and e.task.status == "in_progress"
                         and not e.task.is_human)
    closed_24h = sum(1 for e in entries if not _is_open(e.task)
                     and _event_time(e) >= ws.now() - timedelta(hours=24))
    return {
        **meta_payload(ws),
        "decisions": {"top": dec["items"][:3], "count": dec["count"],
                      "overdue": dec["overdue"], "on_time": dec["on_time"]},
        "mine": {"today": mine_today, "overdue": overdue, "week": this_week,
                 "later": later},
        "review": review,
        "waiting": waiting,
        "agents_working": agents_working,
        "closed_24h": closed_24h,
        "projects": len(projects),
        "errors": ws.errors[:20],
    }


def projects_payload(ws: Workspace) -> dict:
    entries = _visible(ws.scan(), ws)
    projects = ws.projects()
    rows = []
    for slug, p in projects.items():
        mine = [e for e in entries if e.task.project == slug]
        live = [e for e in mine if not e.archived and _is_open(e.task)]
        today = ws.today()
        overdue = sum(1 for e in live if (d := core.parse_date(e.task.get("due"))) and d < today)
        blocked = sum(1 for e in live if e.task.status == "blocked")
        wip = sum(1 for e in live if not e.task.is_human
                  and e.task.s("type") != "decision")
        last, last_when = _last_move(mine, p["dir"])
        cur = _plan_phase(_read_text(p["dir"] / "PLAN.md"),
                          {e.task.id: e.task.status for e in mine if not e.archived})["current"]
        health = 3 - (1 if overdue else 0) - (1 if blocked else 0)
        if overdue > 3 or wip > p["wip_limit"]:
            health = 1
        rows.append({
            "slug": slug, "name": p["name"], "status": p["status"],
            "open": len(live),
            "yours": sum(1 for e in live if e.task.is_human),
            "decisions": sum(1 for e in live if e.task.s("type") == "decision"),
            "blocked": blocked, "overdue": overdue,
            "wip": wip, "wip_limit": p["wip_limit"],
            "health": max(1, health),
            "last_move": last_when.isoformat(timespec="minutes") if last_when else "",
            "last_title": last.task.title if last else "",
            "last_owner": (last.task.owner if last else ""),
            "phase": cur["title"] if cur else "",
        })
    rows.sort(key=lambda r: (r["status"] != "active", r["health"], -r["open"], r["name"].lower()))
    inbox_open = sum(1 for e in entries if not e.task.project and not e.archived
                     and _is_open(e.task))
    return {"items": rows, "inbox_open": inbox_open}


PHASE_WORD = re.compile(r"\b(phase|stage|milestone|step|sprint|faza|etap|krok)\b", re.IGNORECASE)
CURRENT_MARK = re.compile(r"\((current|bieżąca|bieżący|obecna|obecny)\)|status:\s*(active|current)",
                          re.IGNORECASE)
TASK_REF = re.compile(r"\b([AH]-\d{1,6})\b")


def _plan_phase(plan_text: str, statuses: dict | None = None) -> dict:
    """Phases are the H2 sections of PLAN.md that look like phases (the word "Phase",
    "Stage", ... or checkboxes). Progress counts checkboxes and the task IDs a phase
    mentions, using the tasks' real status. Current = marked "(current)", else the
    first phase with open work."""
    statuses = statuses or {}
    phases = []
    for m in re.finditer(r"^##\s+(.+)$", plan_text or "", re.MULTILINE):
        start = m.end()
        nxt = re.search(r"^##\s+", plan_text[start:], re.MULTILINE)
        chunk = plan_text[start: start + nxt.start()] if nxt else plan_text[start:]
        title = m.group(1).strip()
        done = len(re.findall(r"^\s*[-*]\s+\[[xX]\]", chunk, re.MULTILINE))
        open_ = len(re.findall(r"^\s*[-*]\s+\[ \]", chunk, re.MULTILINE))
        if not PHASE_WORD.search(title) and not (done or open_):
            continue
        for ref in dict.fromkeys(TASK_REF.findall(chunk)):
            st = statuses.get(ref)
            if st is None:
                continue
            if st in core.CLOSED_STATUSES:
                done += 1
            else:
                open_ += 1
        phases.append({"title": CURRENT_MARK.sub("", title).strip(), "done": done,
                       "open": open_, "current": bool(CURRENT_MARK.search(title + chunk))})
    current = next((p for p in phases if p["current"]), None)         or next((p for p in phases if p["open"]), None)
    return {"phases": phases, "current": current}


def _log_entries(log_text: str, limit: int = 5) -> list[dict]:
    items = []
    heading_date = ""
    for line in (log_text or "").splitlines():
        s = line.strip()
        hm = re.match(r"^#{2,4}\s+(.*)$", s)
        if hm:
            dm = STAMP_RE.match(hm.group(1))
            heading_date = dm.group(1) if dm else heading_date
            continue
        if not s.startswith(("- ", "* ")):
            continue
        text = s[2:].strip()
        m = STAMP_RE.match(text)
        when = m.group(0) if m else heading_date
        if m:
            text = text[m.end():].lstrip(" —–-:").strip()
        items.append({"when": when, "text": text})
    dated = [i for i in items if i["when"]]
    if dated:
        dated.sort(key=lambda i: i["when"], reverse=True)
        return dated[:limit]
    return list(reversed(items[-limit:]))


def project_payload(ws: Workspace, slug: str) -> dict | None:
    if not SLUG_RE.match(slug or ""):
        return None
    projects = ws.projects()
    p = projects.get(slug)
    if p is None:
        return None
    entries = _visible(ws.scan(), ws)
    counts = _unblock_counts(entries)
    mine = [e for e in entries if e.task.project == slug]
    doc = p["doc"]
    body = doc.body if doc else ""
    plan = _read_text(p["dir"] / "PLAN.md")
    log_text = _read_text(p["dir"] / "LOG.md")
    live = [e for e in mine if not e.archived and _is_open(e.task)]
    sums = {e.key: summary(e, ws, projects, counts) for e in mine}
    blockers = []
    for e in live:
        if e.task.status == "blocked":
            s = dict(sums[e.key])
            s["unblocking_action"] = e.task.section("Unblocking action")
            ub = s["unblocked_by"]
            s["unblocked_by_key"] = f"{slug}/{ub}" if ub and f"{slug}/{ub}" in sums else ""
            blockers.append(s)
    yours = sorted((sums[e.key] for e in live if e.task.is_human
                    and e.task.s("type") != "decision"),
                   key=lambda s: (-s["unblocks"],) + _due_key(s))
    agents = sorted((sums[e.key] for e in live if not e.task.is_human
                     and e.task.s("type") != "decision"), key=_due_key)
    decisions = sorted((sums[e.key] for e in live if e.task.s("type") == "decision"),
                       key=_due_key)
    recent_closed = sorted((sums[e.key] for e in mine if not _is_open(e.task)
                            and _recent(e, ws)), key=lambda s: s["closed"], reverse=True)
    wip = sum(1 for e in live if not e.task.is_human and e.task.s("type") != "decision")
    return {
        "slug": slug, "name": p["name"], "status": p["status"],
        "goal": core.get_section(body, "Goal"),
        "success": core.get_section(body, "Success criteria"),
        "constraints": core.get_section(body, "Constraints"),
        "phase": _plan_phase(plan, {e.task.id: e.task.status for e in mine if not e.archived}),
        "wip": wip, "wip_limit": p["wip_limit"],
        "blockers": blockers, "decisions": decisions,
        "yours": yours, "agents": agents, "recent_closed": recent_closed[:20],
        "log": _log_entries(log_text),
        "tree": dependency_tree(ws, slug, entries=entries, projects=projects),
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return ""


# ── dependency tree ───────────────────────────────────────────────────────────

def dependency_tree(ws: Workspace, slug: str, entries: list[Entry] | None = None,
                    projects: dict | None = None) -> dict:
    """Blocking chains of one project.

    A node's children are the open tasks that wait on it (their `blocked_by` lists it,
    or their `unblocked_by` names it). Only open blockers create edges. Roots are open
    tasks that block something and wait on nothing open. Tasks with no links go to `lanes`,
    grouped by owner, so the tree also answers "who is on what". Cycles are cut and
    marked instead of recursing forever.
    """
    entries = entries if entries is not None else _visible(ws.scan(), ws)
    projects = projects if projects is not None else ws.projects()
    mine = {e.task.id: e for e in entries if e.task.project == slug and not e.archived}
    counts = _unblock_counts(entries)
    open_ids = {i for i, e in mine.items() if _is_open(e.task)}
    parents: dict[str, set[str]] = {}
    children: dict[str, list[str]] = {}
    for i in open_ids:
        t = mine[i].task
        # only OPEN blockers count: a closed parent is a satisfied edge, drawing it
        # would repeat finished work at the top of the tree
        refs = [r for r in t.list("blocked_by") if r in open_ids]
        ub = str(t.get("unblocked_by") or "").strip()
        if ub in open_ids and ub not in refs:
            refs.append(ub)
        for r in refs:
            if r == i:
                continue
            parents.setdefault(i, set()).add(r)
            children.setdefault(r, []).append(i)
    for k in children:
        children[k].sort(key=lambda c: _due_key(summary(mine[c], ws, projects)))

    linked = set(parents) | set(children)
    roots = [i for i in linked if not parents.get(i)]

    rendered: set[str] = set()

    def node(i: str, path: tuple) -> dict:
        s = summary(mine[i], ws, projects, counts)
        n = {k: s[k] for k in ("key", "id", "title", "owner", "human", "type", "status",
                               "due", "overdue_days", "unblocks", "working")}
        n["waits_on"] = sorted(parents.get(i, ()))
        if i in path:
            n["cycle"] = True
            n["children"] = []
            return n
        if i in rendered:
            # a task waiting on two blockers is drawn once; later mentions point to it
            n["ref"] = True
            n["children"] = []
            return n
        rendered.add(i)
        n["children"] = [node(c, path + (i,)) for c in children.get(i, [])]
        return n

    roots.sort(key=lambda i: (-len(children.get(i, [])),) + _due_key(summary(mine[i], ws, projects)))
    chains = [node(r, ()) for r in roots]
    # open tasks that sit only in a cycle never become roots; surface them
    reached: set[str] = set()

    def walk(n):
        reached.add(n["id"])
        for c in n["children"]:
            walk(c)
    for c in chains:
        walk(c)
    for i in sorted(linked & open_ids - reached):
        chains.append(node(i, ()))
        walk(chains[-1])

    lanes: dict[str, list] = {}
    for i in sorted(open_ids - linked):
        s = summary(mine[i], ws, projects, counts)
        lane = "you" if s["human"] else (s["owner"] or "unassigned")
        lanes.setdefault(lane, []).append({k: s[k] for k in (
            "key", "id", "title", "owner", "human", "type", "status", "due",
            "priority", "overdue_days", "working")})
    order = ["you", "ceo", "soft", "web", "copy", "marketing", "research"]
    lane_list = [{"lane": k, "tasks": sorted(v, key=_due_key)}
                 for k, v in sorted(lanes.items(),
                                    key=lambda kv: (order.index(kv[0]) if kv[0] in order
                                                    else len(order), kv[0]))]
    return {"chains": chains, "lanes": lane_list,
            "linked": len(linked & open_ids), "open": len(open_ids)}


def tree_payload(ws: Workspace) -> dict:
    entries = _visible(ws.scan(), ws)
    projects = ws.projects()
    out = []
    for slug, p in projects.items():
        tree = dependency_tree(ws, slug, entries=entries, projects=projects)
        if not tree["open"] and p["status"] != "active":
            continue
        out.append({"slug": slug, "name": p["name"], "status": p["status"], **tree})
    out.sort(key=lambda r: (-r["linked"], -r["open"], r["name"].lower()))
    return {"projects": out}


# ── activity ──────────────────────────────────────────────────────────────────

def activity_payload(ws: Workspace, since: datetime | None, archive: bool = False) -> dict:
    now = ws.now()
    default = now - timedelta(hours=24)
    since = since or default
    clamped = False
    floor = now - timedelta(days=RECENT_DAYS)
    if since < floor - timedelta(hours=1) and not archive:
        since, clamped = floor, True
    elif since < floor and not archive:
        since = floor
    entries = _visible(ws.scan(), ws)
    projects = ws.projects()
    groups: dict[str, dict] = {}
    accepted = rejected = 0
    total = 0
    for e in entries:
        t = e.task
        if _is_open(t):
            continue
        when = _event_time(e)
        if when < since:
            continue
        s = summary(e, ws, projects)
        if t.status == "cancelled":
            kind = "cancelled"
        elif s["type"] == "decision":
            kind = "decided"
            if s["decision"] == "accepted":
                accepted += 1
            elif s["decision"] == "rejected":
                rejected += 1
        elif t.is_human:
            kind = "you"
        else:
            kind = "agent"
        s["kind"] = kind
        s["when"] = when.isoformat(timespec="minutes")
        g = groups.setdefault(t.project or "", {
            "slug": t.project, "name": s["project_name"], "items": [],
            "done": 0, "cancelled": 0})
        g["items"].append(s)
        g["cancelled" if kind == "cancelled" else "done"] += 1
        total += 1
    out = sorted(groups.values(), key=lambda g: -len(g["items"]))
    for g in out:
        g["items"].sort(key=lambda s: s["when"], reverse=True)
    working = [summary(e, ws, projects) for e in entries
               if not e.archived and e.task.status == "in_progress" and not e.task.is_human]
    return {"since": since.isoformat(timespec="minutes"), "clamped": clamped,
            "total": total, "groups": out, "accepted": accepted, "rejected": rejected,
            "working": working}


def tasks_payload(ws: Workspace, scope: str = "open") -> dict:
    entries = _visible(ws.scan(), ws)
    projects = ws.projects()
    counts = _unblock_counts(entries)
    out = []
    for e in entries:
        if scope == "open" and (e.archived or not _is_open(e.task)):
            continue
        if scope == "recent" and not _recent(e, ws):
            continue
        out.append(summary(e, ws, projects, counts))
    out.sort(key=lambda s: (s["status"] in core.CLOSED_STATUSES,) + _due_key(s))
    return {"scope": scope, "items": out, "count": len(out)}


def task_payload(ws: Workspace, entry: Entry) -> dict:
    projects = ws.projects()
    entries = ws.scan()
    counts = _unblock_counts(entries)
    t = entry.task
    s = summary(entry, ws, projects, counts)
    code, rparams, reason = run_now_block(entry)
    closed = t.status in core.CLOSED_STATUSES
    can_edit = not entry.archived
    try:
        mtime_ns = entry.task.path.stat().st_mtime_ns
    except OSError:
        mtime_ns = 0
    waiting_on_this = [e.key for e in entries if e.task.project == t.project and t.id
                       and _is_open(e.task) and not e.archived
                       and (t.id in e.task.list("blocked_by")
                            or str(e.task.get("unblocked_by") or "").strip() == t.id)]
    return {
        **s,
        "body": t.body,
        "created": str(t.get("created") or ""),
        "source": t.s("source"),
        "rel_path": ws.rel(t.path),
        "mtime_ns": str(mtime_ns),
        "waiting_on_this": waiting_on_this,
        "actions": {
            "done": can_edit and not closed,
            "cancel": can_edit and not closed,
            "decide": can_edit and not closed and s["type"] == "decision",
            "note": can_edit,
            "edit": can_edit,
            "run_now": not reason,
        },
        "run_now_reason": reason,
        "run_now_code": code,
        "run_now_params": rparams,
        "archived_reason": "Archived tasks are read-only in the panel." if entry.archived else "",
    }


# ── organisation tree ─────────────────────────────────────────────────────────

ROLE_ORDER = ("ceo", "soft", "web", "copy", "marketing", "research", "human", "")


def _org_task(s: dict) -> dict:
    return {
        "kind": "task", "key": s["key"], "id": s["id"], "title": s["title"],
        "status": s["status"], "priority": s["priority"], "due": s["due"],
        "overdue_days": s["overdue_days"], "decision": s["type"] == "decision",
        "human": s["human"], "working": s["working"],
        "open": 1, "in_progress": 1 if s["status"] == "in_progress" else 0,
        "blocked": 1 if s["status"] == "blocked" else 0,
        "overdue": 1 if s["overdue_days"] > 0 else 0, "mine": 1 if s["human"] else 0,
    }


def _org_task_sort(n: dict):
    return ({"in_progress": 0, "blocked": 1, "todo": 2}.get(n["status"], 3), -n["overdue_days"],
            core.PRIORITY_RANK.get(n["priority"], 1), n["due"] or "9999-99-99", n["id"])


def _sum(nodes: list, field: str) -> int:
    return sum(n[field] for n in nodes)


def org_tree_payload(ws: Workspace) -> dict:
    """Who works on what: owner -> projects -> roles (agents and the owner) -> open tasks.

    Same data as every other screen (one scan, `summary`), only regrouped. Projects with
    work in progress come first, then blocked ones, then by size, so the "hot" part of
    the portfolio is at the top. Inbox tasks without a project form their own branch.
    Labels (role names, "Inbox") are translated by the panel, not here."""
    entries = _visible(ws.scan(), ws)
    projects = ws.projects()
    by_project: dict[str, dict[str, list]] = {}
    for e in entries:
        if e.archived or not _is_open(e.task):
            continue
        s = summary(e, ws, projects)
        slug = e.task.project or ""
        role = "human" if s["human"] else (s["owner"] if s["owner"] in core.ROLES else
                                           (s["owner"] or ""))
        by_project.setdefault(slug, {}).setdefault(role, []).append(_org_task(s))
    out = []
    for slug, roles in by_project.items():
        p = projects.get(slug, {})
        role_nodes = []
        for role, tasks in roles.items():
            tasks.sort(key=_org_task_sort)
            role_nodes.append({
                "kind": "role", "role": role, "slug": slug, "children": tasks,
                "open": len(tasks), "in_progress": _sum(tasks, "in_progress"),
                "blocked": _sum(tasks, "blocked"), "overdue": _sum(tasks, "overdue"),
                "mine": _sum(tasks, "mine"),
            })
        role_nodes.sort(key=lambda r: (ROLE_ORDER.index(r["role"]) if r["role"] in ROLE_ORDER
                                       else len(ROLE_ORDER) - 1, r["role"]))
        tasks = [t for r in role_nodes for t in r["children"]]
        doc = p.get("doc")
        goal = core.get_section(doc.body, "Goal") if doc else ""
        out.append({
            "kind": "project", "slug": slug, "inbox": not slug,
            "name": p.get("name", slug), "status": p.get("status", "active"),
            "goal": re.sub(r"\s+", " ", goal).strip()[:200],
            "wip_limit": p.get("wip_limit", 0),
            "open": len(tasks), "in_progress": _sum(tasks, "in_progress"),
            "blocked": _sum(tasks, "blocked"), "overdue": _sum(tasks, "overdue"),
            "mine": _sum(tasks, "mine"), "decisions": sum(1 for t in tasks if t["decision"]),
            "working_titles": [t["title"] for t in tasks if t["status"] == "in_progress"][:3],
            "children": role_nodes,
        })
    out.sort(key=lambda p: (p["inbox"], -p["in_progress"], -p["blocked"], -p["open"],
                            p["name"].lower()))
    root = {"kind": "root", "name": str(ws.cfg.get("owner_name") or "Owner"),
            "open": _sum(out, "open"), "in_progress": _sum(out, "in_progress"),
            "blocked": _sum(out, "blocked"), "overdue": _sum(out, "overdue"),
            "mine": _sum(out, "mine"), "children": out}
    return {
        "generated": ws.now().isoformat(timespec="minutes"),
        "root": root,
        "stats": {"projects": sum(1 for p in out if not p["inbox"]), "open": root["open"],
                  "in_progress": root["in_progress"], "blocked": root["blocked"],
                  "overdue": root["overdue"], "mine": root["mine"],
                  "roles": len({r["role"] for p in out for r in p["children"]})},
        "errors": ws.errors[:20],
    }
