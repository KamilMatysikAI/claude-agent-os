"""Write side of the panel: actions on tasks, the undo window, run-now and new items.

Rules:
- Every action names a task by KEY. The file path is taken from the scanned index,
  never from the request.
- Archived tasks are read-only. Run-now is refused, with the reason, for anything the
  queue would not take anyway (your own tasks, decisions, `autonomy: ask`, not waiting,
  already locked) — a button that "works" but never starts a run is worse than none.
- Closing actions (done, cancel, decide) wait UNDO_SECONDS before they touch the file,
  so the owner can take back a mis-tap. Validation happens up front; the write itself
  re-reads the file fresh. If the server stops inside the window, pending actions are
  applied (flushed), not dropped.
"""

from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path

from agentos import core
from agentos import env as engine_env

from . import data

UNDO_SECONDS = 5.0
MAX_TEXT = 20_000
MAX_TITLE = 200
DELAYED = ("done", "cancel", "decide")
IMMEDIATE = ("note", "edit", "run-now")
PRIORITIES = ("high", "normal", "low")
PACKAGE_ROOT = Path(__file__).resolve().parent.parent


class ActionError(Exception):
    """`message` is English (logs, API clients); `code` + `params` let the panel show the
    same error in the owner's language (keys `srv.<code>` in the panel dictionaries)."""

    def __init__(self, message: str, status: int = 400, code: str = "", **params):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.params = {k: str(v) for k, v in params.items()}

    def public(self) -> dict:
        return {"error": self.message, "code": self.code, "params": self.params}


def _msg(message: str, code: str, **params) -> dict:
    """A success message with its translation key (see ActionError)."""
    return {"message": message, "msg_code": code,
            "msg_params": {k: str(v) for k, v in params.items()}}


def _text(payload: dict, name: str, limit: int = MAX_TEXT) -> str:
    value = payload.get(name, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ActionError(f"Field '{name}' must be text.", code="field_text", name=name)
    value = value.replace("\r\n", "\n").strip()
    if len(value) > limit:
        raise ActionError(f"Field '{name}' is too long (max {limit} characters).",
                          code="field_long", name=name, limit=limit)
    return value


def _one_line(payload: dict, name: str, limit: int = MAX_TITLE) -> str:
    value = _text(payload, name, limit)
    if "\n" in value:
        raise ActionError(f"Field '{name}' must be a single line.", code="field_line", name=name)
    return value


def _label(entry: data.Entry) -> str:
    return entry.task.id or entry.key


# ── pending actions (undo window) ─────────────────────────────────────────────

class Pending:
    def __init__(self, ws: data.Workspace, delay: float = UNDO_SECONDS):
        self.ws = ws
        self.delay = delay
        self._items: dict[str, dict] = {}
        self._lock = threading.Lock()

    def schedule(self, action: str, key: str, params: dict) -> dict:
        pid = secrets.token_hex(8)
        item = {"id": pid, "action": action, "key": key, "params": params,
                "status": "pending", "error": "", "error_code": "", "error_params": {},
                "created": time.time()}
        timer = threading.Timer(self.delay, self._fire, args=(pid,))
        timer.daemon = True
        item["timer"] = timer
        with self._lock:
            self._gc()
            if any(i["key"] == key and i["status"] == "pending" for i in self._items.values()):
                raise ActionError("Another action on this task is still in its undo window.",
                                  409, code="undo_busy")
            self._items[pid] = item
            self.ws.hidden_keys.add(key)
        timer.start()
        return self.public(item)

    def undo(self, pid: str) -> dict:
        with self._lock:
            item = self._items.get(pid)
            if item is None:
                raise ActionError("Nothing to undo: unknown or expired action.", 404,
                                  code="undo_unknown")
            if item["status"] != "pending":
                raise ActionError(f"Too late to undo: the action is already {item['status']}.",
                                  409, code="undo_late", state=item["status"])
            item["timer"].cancel()
            item["status"] = "undone"
            self.ws.hidden_keys.discard(item["key"])
            return self.public(item)

    def get(self, pid: str) -> dict | None:
        with self._lock:
            item = self._items.get(pid)
            return self.public(item) if item else None

    def flush(self) -> None:
        """Apply everything still pending (server shutdown)."""
        with self._lock:
            ids = [i["id"] for i in self._items.values() if i["status"] == "pending"]
        for pid in ids:
            with self._lock:
                item = self._items.get(pid)
                if item:
                    item["timer"].cancel()
            self._fire(pid)

    def _fire(self, pid: str) -> None:
        with self._lock:
            item = self._items.get(pid)
            if item is None or item["status"] != "pending":
                return
            item["status"] = "applying"
        code, cparams = "", {}
        try:
            apply_delayed(self.ws, item["action"], item["key"], item["params"])
            status, error = "applied", ""
        except ActionError as exc:
            status, error, code, cparams = "failed", exc.message, exc.code, exc.params
        except Exception as exc:  # noqa: BLE001 - reported to the client, never raised
            status, error = "failed", f"Could not save: {exc}"
            code, cparams = "save_failed", {"detail": str(exc)}
        with self._lock:
            item["status"], item["error"] = status, error
            item["error_code"], item["error_params"] = code, cparams
            self.ws.hidden_keys.discard(item["key"])
        if status == "failed":
            core.log(self.ws.root, "panel", f"action {item['action']} {item['key']} failed: {error}")

    def _gc(self) -> None:
        cutoff = time.time() - 600
        for pid in [p for p, i in self._items.items()
                    if i["status"] != "pending" and i["created"] < cutoff]:
            self._items.pop(pid, None)

    @staticmethod
    def public(item: dict) -> dict:
        return {k: item[k] for k in ("id", "action", "key", "status", "error",
                                      "error_code", "error_params")}


# ── validation ────────────────────────────────────────────────────────────────

def _entry(ws: data.Workspace, key: str) -> data.Entry:
    if not isinstance(key, str) or not data.valid_key(key):
        raise ActionError("Unknown task.", 404, code="unknown_task")
    entry = ws.find(key)
    if entry is None:
        raise ActionError("Unknown task.", 404, code="unknown_task")
    return entry


def validate(ws: data.Workspace, action: str, key: str, payload: dict) -> tuple[data.Entry, dict]:
    if action not in DELAYED + IMMEDIATE:
        raise ActionError(f"Unknown action '{action}'.", code="unknown_action", action=action)
    entry = _entry(ws, key)
    t = entry.task
    if entry.archived:
        raise ActionError(f"{_label(entry)} is archived. Archived tasks are read-only in the panel.",
                          code="archived", id=_label(entry))
    closed = t.status in core.CLOSED_STATUSES
    params: dict = {}
    if action in DELAYED and closed:
        raise ActionError(f"{_label(entry)} is already {t.status}.", code="already_closed",
                          id=_label(entry), state=t.status)
    if action == "done":
        evidence = _text(payload, "evidence", 1000)
        if not evidence and not str(t.get("evidence") or "").strip():
            raise ActionError("Add evidence before closing: a file path, a link or a test result.",
                              code="evidence_required")
        if t.s("type") == "decision":
            raise ActionError("Decisions are closed by accepting or rejecting them.",
                              code="decision_needs_decide")
        params = {"evidence": evidence, "note": _text(payload, "note")}
    elif action == "cancel":
        params = {"note": _text(payload, "note")}
    elif action == "decide":
        if t.s("type") != "decision":
            raise ActionError(f"{_label(entry)} is not a decision.", code="not_decision",
                              id=_label(entry))
        accepted = payload.get("accepted")
        if not isinstance(accepted, bool):
            raise ActionError("Say whether the decision is accepted (true) or rejected (false).",
                              code="decide_bool")
        params = {"accepted": accepted, "note": _text(payload, "note")}
    elif action == "note":
        note = _text(payload, "note")
        if not note:
            raise ActionError("The note is empty.", code="note_empty")
        params = {"note": note}
    elif action == "edit":
        params = _validate_edit(entry, payload)
    elif action == "run-now":
        code, rparams, reason = data.run_now_block(entry)
        if reason:
            raise ActionError(reason, code=code, **rparams)
    return entry, params


def _validate_edit(entry: data.Entry, payload: dict) -> dict:
    params: dict = {}
    base = str(payload.get("mtime_ns") or "")
    try:
        current = str(entry.task.path.stat().st_mtime_ns)
    except OSError:
        current = ""
    if not base or base != current:
        raise ActionError("This task changed since you opened it. Reload it and edit again.", 409,
                          code="changed_since")
    if "title" in payload:
        title = _one_line(payload, "title")
        if not title:
            raise ActionError("The title cannot be empty.", code="title_empty")
        params["title"] = title
    if "priority" in payload:
        pr = _one_line(payload, "priority", 10).lower()
        if pr not in PRIORITIES:
            raise ActionError("Priority must be high, normal or low.", code="priority_invalid")
        params["priority"] = pr
    if "due" in payload:
        due = _one_line(payload, "due", 10)
        if due and core.parse_date(due) is None:
            raise ActionError("Due date must look like 2026-10-20.", code="due_invalid")
        params["due"] = due
    if "body" in payload:
        body = _text(payload, "body", 200_000)
        if re.search(r"^---\s*$", body.split("\n", 1)[0] if body else ""):
            raise ActionError("The body cannot start with a frontmatter fence (---).",
                              code="body_frontmatter")
        params["body"] = body
    if not params:
        raise ActionError("Nothing to change.", code="nothing_to_change")
    return params


# ── applying ──────────────────────────────────────────────────────────────────

def apply_delayed(ws: data.Workspace, action: str, key: str, params: dict) -> None:
    entry = _entry(ws, key)
    if entry.archived:
        raise ActionError("The task was archived in the meantime; nothing was changed.",
                          code="archived_meantime")
    task = core.read_task(entry.task.path)   # fresh read: someone may have edited it
    if task.status in core.CLOSED_STATUSES:
        raise ActionError(f"{task.id or key} was closed in the meantime ({task.status}).",
                          code="closed_meantime", id=task.id or key, state=task.status)
    now = ws.now()
    if action == "done":
        if params.get("note"):
            core.add_note(task, params["note"], now=now, write=False)
        try:
            core.set_status(task, "done", evidence=params.get("evidence") or None,
                            note="closed from the panel", now=now)
        except core.EvidenceRequired as exc:
            raise ActionError(str(exc), code="evidence_required") from exc
    elif action == "cancel":
        if params.get("note"):
            core.add_note(task, params["note"], now=now, write=False)
        core.set_status(task, "cancelled", note="cancelled from the panel", now=now)
    elif action == "decide":
        core.decide(task, bool(params["accepted"]), params.get("note", ""), now=now)


def apply_immediate(ws: data.Workspace, action: str, entry: data.Entry, params: dict,
                    spawn=None) -> dict:
    now = ws.now()
    if action == "note":
        task = core.read_task(entry.task.path)
        core.add_note(task, params["note"], now=now)
        return _msg(f"Note added to {_label(entry)}.", "note_added", id=_label(entry))
    if action == "edit":
        task = core.read_task(entry.task.path)
        for field in ("title", "priority", "due"):
            if field in params:
                task.meta[field] = params[field]
        if "body" in params:
            body = params["body"]
            task.body = ("\n" + body.strip("\n") + "\n") if body.strip() else "\n"
        core.write_task_atomic(task)
        return _msg(f"Saved {_label(entry)}.", "saved", id=_label(entry))
    if action == "run-now":
        return run_now(ws, entry, spawn=spawn)
    raise ActionError(f"Unknown action '{action}'.", code="unknown_action", action=action)


def run_now(ws: data.Workspace, entry: data.Entry, spawn=None) -> dict:
    rel = ws.rel(entry.task.path)
    result = core.request_run_now(ws.root, rel, who="panel")
    if result == "busy":
        raise ActionError("The queue is reading its requests right now. Try again in a moment.",
                          409, code="queue_busy")
    if result == "duplicate":
        return {**_msg(f"{_label(entry)} is already waiting for a run.", "run_already",
                        id=_label(entry)), "started": False}
    core.append_progress(entry.task.path, "run requested from the panel", now=ws.now())
    starter = spawn or spawn_runner
    ok, detail = starter(ws.root, entry.task.path)
    if ok:
        return {**_msg(f"Started a run for {_label(entry)}.", "run_started", id=_label(entry)),
                "started": True}
    return {**_msg(f"Queued {_label(entry)}. It will run on the next scheduled pass; "
                   f"starting now failed: {detail}", "run_queued", id=_label(entry), detail=detail),
            "started": False}


def spawn_runner(workspace: Path, task_path: Path) -> tuple[bool, str]:
    """Start `python -m agentos run --task PATH` detached from the panel process, so a
    long run survives a panel restart and never blocks a request."""
    try:  # the CLI documents --task as relative to the workspace
        task_arg = Path(task_path).resolve().relative_to(Path(workspace).resolve()).as_posix()
    except ValueError:
        task_arg = str(task_path)
    # The workspace venv (normal install) when it exists, like the scheduler's tick.py.
    # -P: the cwd is the agent-writable workspace and must never be on sys.path.
    python = engine_env.engine_python(workspace)
    cmd = [python, "-P", "-m", "agentos", "run", "--task", task_arg,
           "--workspace", str(workspace)]
    env = dict(os.environ)
    if not engine_env.has_venv(workspace):  # fallback: the package this panel runs from
        env["PYTHONPATH"] = os.pathsep.join(p for p in (str(PACKAGE_ROOT), env.get("PYTHONPATH", ""))
                                            if p)
    logs = core.state_dir(workspace) / "logs"
    try:
        logs.mkdir(parents=True, exist_ok=True)
        out = open(logs / "run-now.log", "ab")  # noqa: SIM115 - handed to the child
    except OSError as exc:
        return False, f"cannot open the log: {exc}"
    kwargs: dict = {"cwd": str(workspace), "env": env, "stdin": subprocess.DEVNULL,
                    "stdout": out, "stderr": subprocess.STDOUT, "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0x8)
                                   | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
                                   | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(cmd, **kwargs)  # noqa: S603 - fixed argv, no shell
        return True, ""
    except OSError as exc:
        return False, str(exc)
    finally:
        out.close()


# ── new task / idea ───────────────────────────────────────────────────────────

def create(ws: data.Workspace, payload: dict) -> dict:
    kind = _one_line(payload, "kind", 10) or "task"
    title = _one_line(payload, "title")
    if not title:
        raise ActionError("Give it a title.", code="title_required")
    details = _text(payload, "details")
    if kind == "idea":
        return _create_idea(ws, title, details)
    if kind != "task":
        raise ActionError("Kind must be 'task' or 'idea'.", code="kind_invalid")
    project = _one_line(payload, "project", 80)
    if project and project not in ws.projects():
        raise ActionError("Unknown project.", code="unknown_project")
    owner = (_one_line(payload, "owner", 20) or "ceo").lower()
    if owner not in core.ROLES:
        raise ActionError(f"Owner must be one of: {', '.join(core.ROLES)}.", code="owner_invalid",
                          roles=", ".join(core.ROLES))
    priority = (_one_line(payload, "priority", 10) or "normal").lower()
    if priority not in PRIORITIES:
        raise ActionError("Priority must be high, normal or low.", code="priority_invalid")
    due = _one_line(payload, "due", 10)
    if due and core.parse_date(due) is None:
        raise ActionError("Due date must look like 2026-10-20.", code="due_invalid")
    sections = {"Goal": details or title, "Progress log": ""}
    task = core.create_task(ws.root, title, owner=owner, project=project, priority=priority,
                            due=due or None, source="panel", sections=sections,
                            today=ws.today())
    ws.scan()
    key = f"{project}/{task.id}" if project else \
        f"{data.INBOX}/{core.slugify(task.path.stem, max_len=160)}"
    where = "your list" if owner == "human" else ("the queue" if not project
                                                   else f"{project}")
    code = "created_mine" if owner == "human" else ("created_queue" if not project
                                                    else "created_project")
    name = ws.projects().get(project, {}).get("name", project) if project else ""
    return {"key": key, "id": task.id,
            **_msg(f"Created {task.id or title} in {where}.", code, id=task.id or title,
                   project=name)}


# Installed copy: packaged next to this module (see pyproject.toml); checkout: repo template/.
_HERE = Path(__file__).resolve().parent
PACKAGED_IDEA_TEMPLATE = next(
    (p for p in (_HERE / "_idea_template" / "idea.md",
                 PACKAGE_ROOT / "template" / "ideas" / ".templates" / "idea.md") if p.is_file()),
    PACKAGE_ROOT / "template" / "ideas" / ".templates" / "idea.md")
IDEAS_INDEX_SCRIPT = next(
    (p for p in (_HERE / "_add_idea" / "ideas_index.py",
                 PACKAGE_ROOT / "template" / ".claude" / "skills" / "add-idea" / "scripts"
                 / "ideas_index.py") if p.is_file()),
    PACKAGE_ROOT / "template" / ".claude" / "skills" / "add-idea" / "scripts" / "ideas_index.py")
FALLBACK_IDEA_TEMPLATE = """---
title: Idea name
status: new
category: other
potential: medium
effort: medium
tags: []
project:
created: YYYY-MM-DD
---

# Idea name

## What it is

## Problem it solves

## Potential

## Risks

## Rough cost

## Notes
"""


def _idea_template(ws: data.Workspace) -> str:
    """The workspace's own template (the owner may have edited it), else the packaged one."""
    for path in (ws.root / "ideas" / ".templates" / "idea.md", PACKAGED_IDEA_TEMPLATE):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if text.startswith("---"):
            return text.replace("\r\n", "\n")
    return FALLBACK_IDEA_TEMPLATE


def _fill_section(body: str, heading: str, text: str) -> str:
    """Put `text` under `## heading`, replacing the template's <!-- hint --> comment."""
    m = re.search(rf"^## {re.escape(heading)}[ \t]*\n", body, re.M)
    if not m:
        return body.rstrip("\n") + f"\n\n## {heading}\n\n{text}\n"
    nxt = re.search(r"^## ", body[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(body)
    return body[:m.end()] + f"\n{text}\n\n" + body[end:].lstrip("\n")


def render_idea(template: str, title: str, details: str, today: str) -> str:
    """Fill the add-idea template: same fields and sections the /add-idea skill writes."""
    _, fm, body = template.split("---", 2)
    lines, seen = [], set()
    for line in fm.strip("\n").split("\n"):
        key = line.split(":", 1)[0].strip()
        if key == "title":
            line = f"title: {core.format_value(title)}"
        elif key == "created":
            line = f"created: {today}"
        seen.add(key)
        lines.append(line)
    for key, value in (("title", core.format_value(title)), ("status", "new"),
                       ("created", today)):
        if key not in seen:
            lines.append(f"{key}: {value}")
    body = re.sub(r"^# .*$", f"# {title}", body.lstrip("\n"), count=1, flags=re.M)
    body = _fill_section(body, "What it is", details or title)
    body = _fill_section(body, "Notes", f"- {today} — added from the panel.")
    return "---\n" + "\n".join(lines) + "\n---\n\n" + body.rstrip("\n") + "\n"


def _refresh_ideas_index(ws: data.Workspace, folder: Path) -> None:
    """Regenerate ideas/index.md with the packaged add-idea script. The workspace copy of
    the script is agent-writable, so the panel never imports that one."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_agentos_ideas_index", IDEAS_INDEX_SCRIPT)
        if spec is None or spec.loader is None:
            return
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        (folder / module.INDEX_NAME).write_text(module.build_index(folder), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - the idea itself is saved; the index is a view
        core.log(ws.root, "panel", f"ideas index not refreshed: {exc!r}")


def _create_idea(ws: data.Workspace, title: str, details: str) -> dict:
    folder = ws.root / "ideas"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        text = render_idea(_idea_template(ws), title, details, ws.today().isoformat())
    except ValueError:
        text = render_idea(FALLBACK_IDEA_TEMPLATE, title, details, ws.today().isoformat())
    base = core.slugify(title)
    for n in range(1, 200):
        path = folder / (f"{base}.md" if n == 1 else f"{base}-{n}.md")
        if path.name == "index.md":
            continue
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as fh:
            fh.write(text.encode("utf-8"))
        _refresh_ideas_index(ws, folder)
        return {"key": "", "id": "",
                **_msg(f"Saved the idea to ideas/{path.name}.", "idea_saved",
                       file=f"ideas/{path.name}")}
    raise ActionError("Could not find a free file name for the idea.", 500, code="idea_name")


def parse_since(value: str) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            moment = datetime.combine(date.fromisoformat(value[:10]), datetime.min.time())
        except ValueError:
            return None
    if moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment
