"""Library API shared by the CLI, the guard, the runner, the panel and the installer.

Design rules (each one comes from a real failure of the system this was ported from):
- One bad file never breaks a scan: `iter_tasks` skips unreadable files and reports them.
- Writes are atomic (temp file + os.replace) with a short retry, because on Windows an
  indexer or antivirus can hold a file for a fraction of a second.
- Frontmatter round-trips: unknown keys, their order, comments and the body survive a write.
  Only keys whose value actually changed are re-rendered.
- A task lock is taken only after a FRESH read of the file, inside an inter-process guard
  (os.open O_CREAT|O_EXCL is atomic on Windows and POSIX). Two runners never hold one task.
- Nothing here deletes user files. The only files removed are our own temp/guard files.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import socket
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import find_workspace, load_config, load_env  # re-exported API  # noqa: F401

STATUSES = ("todo", "in_progress", "blocked", "done", "cancelled")
OPEN_STATUSES = ("todo", "in_progress", "blocked")
CLOSED_STATUSES = ("done", "cancelled")
ROLES = ("ceo", "marketing", "copy", "web", "soft", "research", "human")
TYPES = ("task", "decision", "review")
PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}

SECTION_ORDER = (
    "Goal", "Context", "Steps", "Definition of done", "For approval",
    "Unblocking action", "Owner notes", "Progress log",
)
# Key order used when we create a task from scratch (matches CONTRACT schema).
KEY_ORDER = (
    "id", "project", "title", "owner", "type", "status", "priority", "due", "created",
    "closed", "size", "autonomy", "source", "profile", "blocked_by", "unblocked_by",
    "decision", "evidence", "lock",
)
LIST_KEYS = ("blocked_by",)

LOCK_ALIVE_MIN = 90          # a task lock younger than this belongs to a live run
LOCK_FUTURE_TOLERANCE_MIN = 5  # clock skew tolerance; further in the future = garbage
GUARD_STALE_S = 60           # an O_EXCL guard file older than this is from a killed process
RUN_NOW_TTL_MIN = 240

ID_RE = re.compile(r"^([A-Z])-(\d{1,6})\b")
STATE_DIR = ".agentos"


class EvidenceRequired(ValueError):
    """Raised when a task is set to done without evidence (path, link or test result)."""


class LockBusy(RuntimeError):
    pass


# ── time ──────────────────────────────────────────────────────────────────────

def now_local(cfg: dict | None = None) -> datetime:
    """Naive local time, in the configured timezone when zoneinfo data is available."""
    tz = (cfg or {}).get("timezone") or ""
    if tz:
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(tz)).replace(tzinfo=None)
        except Exception:  # noqa: BLE001 - missing tzdata on Windows: fall back to local
            pass
    return datetime.now()


def stamp(moment: datetime | None = None) -> str:
    return (moment or datetime.now()).strftime("%Y-%m-%d %H:%M")


def parse_date(value) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


# ── frontmatter ──────────────────────────────────────────────────────────────

def _strip_comment(raw: str) -> str:
    """Drop a trailing ` # comment` unless the value is quoted."""
    text = raw.strip()
    if text and text[0] in "\"'":
        quote = text[0]
        end = text.find(quote, 1)
        while end > 0 and quote == '"' and text[end - 1] == "\\":
            end = text.find(quote, end + 1)
        return text[: end + 1] if end > 0 else text
    match = re.search(r"\s#", text)
    return text[: match.start()].rstrip() if match else text


def parse_value(raw: str):
    text = _strip_comment(raw)
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_unquote(item.strip()) for item in inner.split(",") if item.strip()]
    return _unquote(text)


def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        inner = text[1:-1]
        if text[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        else:
            inner = inner.replace("''", "'")
        return inner
    return text


def format_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(format_scalar(v) for v in value) + "]"
    return format_scalar(value)


def format_scalar(value) -> str:
    text = str(value)
    if text == "":
        return ""
    needs_quotes = (
        text != text.strip()
        or ": " in text or " #" in text or text.endswith(":")
        or text[0] in "[]{}#&*!|>'\"%@`,-?"
        or "\n" in text
    )
    if not needs_quotes:
        return text
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{escaped}"'


@dataclass
class Task:
    path: Path
    meta: dict = field(default_factory=dict)
    body: str = ""
    # (key or None, raw lines) as read; key None = comment/blank line inside frontmatter
    _entries: list = field(default_factory=list, repr=False)
    _original: dict = field(default_factory=dict, repr=False)
    _newline: str = field(default="\n", repr=False)
    _has_frontmatter: bool = field(default=True, repr=False)

    def get(self, key: str, default=""):
        value = self.meta.get(key, default)
        return default if value is None else value

    def s(self, key: str) -> str:
        """Lower-cased, stripped scalar (status, owner, type ...)."""
        value = self.meta.get(key, "")
        return value.strip().lower() if isinstance(value, str) else ""

    @property
    def id(self) -> str:
        return str(self.meta.get("id") or "").strip()

    @property
    def status(self) -> str:
        return self.s("status") or "todo"

    @property
    def owner(self) -> str:
        return self.s("owner")

    @property
    def is_human(self) -> bool:
        return self.owner == "human" or self.id.startswith("H-")

    @property
    def project(self) -> str:
        return str(self.meta.get("project") or "").strip()

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or self.path.stem)

    def list(self, key: str) -> list[str]:
        value = self.meta.get(key)
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str) and value.strip():
            return [v.strip() for v in value.split(",") if v.strip()]
        return []

    def section(self, heading: str) -> str:
        return get_section(self.body, heading)


def parse_task_text(text: str, path: Path) -> Task:
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return Task(path=path, meta={}, body=text.replace("\r\n", "\n"),
                    _newline=newline, _has_frontmatter=False)
    entries: list = []
    meta: dict = {}
    end = None
    for index in range(1, len(lines)):
        line = lines[index]
        if line.strip() == "---":
            end = index
            break
        if line[:1].isspace() and entries and entries[-1][0] is not None:
            entries[-1][1].append(line)          # continuation (e.g. "  - A-001")
            continue
        if ":" in line and not line.lstrip().startswith("#"):
            key, raw = line.split(":", 1)
            entries.append((key.strip(), [line]))
        else:
            entries.append((None, [line]))
    if end is None:  # unterminated frontmatter: treat the whole file as body
        return Task(path=path, meta={}, body=text.replace("\r\n", "\n"),
                    _newline=newline, _has_frontmatter=False)
    for key, raw_lines in entries:
        if key is None:
            continue
        first = raw_lines[0].split(":", 1)[1]
        value = parse_value(first)
        items = [ln.strip()[2:].strip() for ln in raw_lines[1:] if ln.strip().startswith("- ")]
        if value == "" and items:
            value = [_unquote(_strip_comment(i)) for i in items]
        meta[key] = value
    body = "\n".join(lines[end + 1:])
    original = {k: (list(v) if isinstance(v, list) else v) for k, v in meta.items()}
    return Task(path=path, meta=meta, body=body, _entries=entries, _original=original,
                _newline=newline)


def render_task(task: Task) -> str:
    out: list[str] = ["---"]
    seen = set()
    for key, raw_lines in task._entries:
        if key is None:
            out.extend(raw_lines)
            continue
        if key in seen:
            continue
        seen.add(key)
        if key not in task.meta:
            continue  # removed by caller
        if task.meta[key] == task._original.get(key):
            out.extend(raw_lines)  # untouched: keep comment, quoting and layout
        else:
            out.append(f"{key}: {format_value(task.meta[key])}".rstrip())
    for key, value in task.meta.items():
        if key not in seen:
            out.append(f"{key}: {format_value(value)}".rstrip())
    out.append("---")
    text = "\n".join(out) + "\n" + task.body
    if not task._has_frontmatter and not task.meta:
        text = task.body
    return text.replace("\n", task._newline) if task._newline != "\n" else text


def read_task(path: str | os.PathLike) -> Task:
    """Strict read (raises OSError/UnicodeDecodeError). utf-8-sig accepts a BOM from
    editors on Windows."""
    p = Path(path)
    with open(p, encoding="utf-8-sig", newline="") as fh:
        return parse_task_text(fh.read(), p)


# ── atomic writes ────────────────────────────────────────────────────────────

def write_text_atomic(path: str | os.PathLike, text: str, retries: int = 8) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    data = text.encode("utf-8")
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
            return
        except PermissionError as exc:  # Windows: file briefly held by indexer/AV
            last = exc
            time.sleep(0.05 * (attempt + 1))
        except OSError as exc:
            last = exc
            break
    with contextlib.suppress(OSError):
        if tmp.exists():
            os.remove(tmp)  # our own temp file, never user data
    raise last  # type: ignore[misc]


def write_task_atomic(task: Task) -> None:
    write_text_atomic(task.path, render_task(task))


# ── inter-process guard ──────────────────────────────────────────────────────

def state_dir(workspace: str | os.PathLike) -> Path:
    return Path(workspace) / STATE_DIR


@contextlib.contextmanager
def file_guard(lock_path: str | os.PathLike, timeout_s: float = 5.0,
               stale_s: float = GUARD_STALE_S):
    """Inter-process mutex. Yields True when acquired, False on timeout (callers must
    degrade gracefully, never hang a scheduled run)."""
    lock = Path(lock_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    fd = None
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                age = 0
            if age > stale_s:
                with contextlib.suppress(OSError):
                    os.remove(lock)  # guard file of a killed process
                continue
            if time.monotonic() >= deadline:
                yield False
                return
            time.sleep(0.05)
        except OSError:
            yield False
            return
    try:
        with contextlib.suppress(OSError):
            os.write(fd, f"{os.getpid()}|{socket.gethostname()}".encode())
        yield True
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(OSError):
            os.remove(lock)


def _guard_path_for(path: Path) -> Path:
    ws = _workspace_of(path)
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", str(path.resolve()))[-120:]
    return state_dir(ws) / "locks" / f"{name}.lock"


def _workspace_of(path: Path) -> Path:
    try:
        return find_workspace(path.parent)
    except Exception:  # noqa: BLE001
        return path.parent


# ── task locks (field `lock: "<ISO>|<host>|<pid>"`) ──────────────────────────

def lock_token() -> str:
    return f"{datetime.now().isoformat(timespec='seconds')}|{socket.gethostname()}|{os.getpid()}"


def lock_alive(value: str, now: datetime | None = None,
               alive_min: int = LOCK_ALIVE_MIN) -> bool:
    if not value or not isinstance(value, str):
        return False
    try:
        taken = datetime.fromisoformat(value.split("|", 1)[0].strip())
    except ValueError:
        return False  # unreadable lock = dead
    if taken.tzinfo is not None:
        taken = taken.astimezone().replace(tzinfo=None)
    age = (now or datetime.now()) - taken
    if age < -timedelta(minutes=LOCK_FUTURE_TOLERANCE_MIN):
        return False  # far in the future = garbage, not a live run
    return age < timedelta(minutes=alive_min)


def acquire_lock(task_or_path, now: datetime | None = None) -> str | None:
    """Take the task lock after a fresh read. Returns the token or None when busy."""
    path = Path(task_or_path.path if isinstance(task_or_path, Task) else task_or_path)
    with file_guard(_guard_path_for(path)) as ok:
        if not ok:
            return None
        task = read_task(path)
        if lock_alive(str(task.get("lock")), now):
            return None
        token = lock_token()
        task.meta["lock"] = token
        write_task_atomic(task)
        return token


def release_lock(task_or_path, token: str | None = None) -> bool:
    """Clear the lock if we still own it (token match). token=None forces release."""
    path = Path(task_or_path.path if isinstance(task_or_path, Task) else task_or_path)
    with file_guard(_guard_path_for(path)) as ok:
        if not ok:
            return False
        try:
            task = read_task(path)
        except OSError:
            return False
        current = str(task.get("lock"))
        if not current:
            return True
        if token is not None and current != token:
            return False  # someone else took over after our lock went stale
        task.meta["lock"] = ""
        write_task_atomic(task)
        return True


# ── discovery ────────────────────────────────────────────────────────────────

def projects_dir(workspace) -> Path:
    return Path(workspace) / "projects"


def iter_project_dirs(workspace):
    root = projects_dir(workspace)
    if not root.is_dir():
        return
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and not entry.name.startswith((".", "_")):
            yield entry


def read_project(project_dir: Path) -> Task | None:
    try:
        return read_task(project_dir / "PROJECT.md")
    except (OSError, UnicodeDecodeError):
        return None


def iter_tasks(workspace, include_inbox: bool = True, recursive: bool = False,
               errors: list | None = None):
    """Yield every task. Files without frontmatter `status` or `id` are not tasks.
    Unreadable files are appended to `errors` (if given) and skipped."""
    sources = []
    for pdir in iter_project_dirs(workspace):
        tdir = pdir / "tasks"
        if tdir.is_dir():
            sources.append((pdir.name, tdir))
    if include_inbox:
        inbox = Path(workspace) / "inbox"
        if inbox.is_dir():
            sources.append(("", inbox))
    for slug, tdir in sources:
        pattern = tdir.rglob("*.md") if recursive and slug else tdir.glob("*.md")
        for path in sorted(pattern):
            if path.name.startswith("."):
                continue
            try:
                task = read_task(path)
            except Exception as exc:  # noqa: BLE001 - one bad file never breaks a scan
                if errors is not None:
                    errors.append(f"{path}: {exc}")
                continue
            if "status" not in task.meta and "id" not in task.meta:
                continue
            if slug and not task.project:
                task.meta["project"] = slug
            yield task


def task_index(tasks) -> dict:
    """{(project, id): task} for ID lookups inside a project."""
    return {(t.project, t.id): t for t in tasks if t.id}


# ── ids and creation ─────────────────────────────────────────────────────────

def next_id(tasks_dir: str | os.PathLike, prefix: str = "A") -> str:
    """max over the whole tasks dir (archives included, filename and frontmatter) + 1.

    The number is SHARED between A- and H- prefixes, so A-012 and H-012 never coexist
    and "#12" is unambiguous inside a project."""
    if prefix not in ("A", "H"):
        raise ValueError("prefix must be A or H")
    root = Path(tasks_dir)
    if (root / "tasks").is_dir():
        root = root / "tasks"
    highest = 0
    if root.is_dir():
        for path in root.rglob("*.md"):
            match = ID_RE.match(path.name)
            if match and match.group(1) in "AH":
                highest = max(highest, int(match.group(2)))
            try:
                with open(path, encoding="utf-8-sig", errors="replace") as fh:
                    head = fh.read(600)
            except OSError:
                continue
            m = re.search(r"^id:\s*['\"]?([AH])-(\d+)", head, re.MULTILINE)
            if m:
                highest = max(highest, int(m.group(2)))
    return f"{prefix}-{highest + 1:03d}"


def slugify(text: str, max_len: int = 50) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return (slug[:max_len].rstrip("-")) or "task"


def _render_sections(sections: dict) -> str:
    parts = []
    for heading in SECTION_ORDER:
        if heading in sections:
            parts.append(f"## {heading}\n\n{str(sections[heading]).strip()}\n")
    for heading, text in sections.items():
        if heading not in SECTION_ORDER:
            parts.append(f"## {heading}\n\n{str(text).strip()}\n")
    return "\n" + "\n".join(parts)


def create_task(workspace, title: str, owner: str = "soft", project: str = "",
                type: str = "task", status: str = "todo", priority: str = "normal",
                due: str | date | None = None, size: str = "small",
                autonomy: str = "full", source: str = "local",
                sections: dict | None = None, today: date | None = None,
                **extra) -> Task:
    """Create a task file with the next free ID. Never overwrites an existing file."""
    ws = Path(workspace)
    today = today or date.today()
    human = owner == "human" or (type == "decision" and owner in ("", "human"))
    prefix = "H" if human else "A"
    meta: dict = {}
    for key in KEY_ORDER:
        meta[key] = ""
    meta.update({
        "project": project, "title": title, "owner": owner or "human", "type": type,
        "status": status, "priority": priority, "due": str(due or ""),
        "created": today.isoformat(), "size": size, "autonomy": autonomy,
        "source": source, "blocked_by": [],
    })
    meta.update({k: v for k, v in extra.items() if v is not None})
    body = _render_sections(sections or {"Goal": title, "Progress log": ""})
    if project:
        tdir = projects_dir(ws) / project / "tasks"
    else:
        tdir = ws / "inbox"
    tdir.mkdir(parents=True, exist_ok=True)
    guard = state_dir(ws) / "locks" / f"ids-{project or 'inbox'}.lock"
    with file_guard(guard, timeout_s=15) as ok:
        if not ok:
            raise LockBusy(f"could not reserve an ID in {tdir}")
        if project or prefix == "H":  # inbox agent tasks stay ID-less (ad hoc)
            meta["id"] = next_id(tdir, prefix)
            base = f"{meta['id']}-{slugify(title)}"
        else:
            meta["id"] = meta.get("id") or ""
            base = slugify(title)
        for n in range(1, 1000):
            name = f"{base}.md" if n == 1 else f"{base}-{n}.md"
            path = tdir / name
            task = Task(path=path, meta=meta, body=body)
            try:
                fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                continue
            with os.fdopen(fd, "wb") as fh:
                fh.write(render_task(task).encode("utf-8"))
            return read_task(path)
    raise LockBusy(f"no free file name for {base}")


# ── sections and state changes ───────────────────────────────────────────────

def get_section(body: str, heading: str) -> str:
    match = re.search(rf"^##\s+{re.escape(heading)}\s*$", body, re.MULTILINE | re.IGNORECASE)
    if not match:
        return ""
    rest = body[match.end():]
    nxt = re.search(r"^##\s+", rest, re.MULTILINE)
    return (rest[: nxt.start()] if nxt else rest).strip()


def append_to_section(body: str, heading: str, line: str) -> str:
    """Append `line` at the end of section `heading`, creating it in canonical order."""
    match = re.search(rf"^##\s+{re.escape(heading)}\s*$", body, re.MULTILINE | re.IGNORECASE)
    if match:
        rest = body[match.end():]
        nxt = re.search(r"^##\s+", rest, re.MULTILINE)
        end = match.end() + (nxt.start() if nxt else len(rest))
        chunk = body[match.end():end].rstrip()
        new_chunk = (chunk + "\n" if chunk else "\n\n") + line + "\n"
        tail = body[end:]
        return body[: match.end()] + new_chunk + ("\n" + tail if tail else "")
    # create before the first later section of the canonical order
    later = SECTION_ORDER[SECTION_ORDER.index(heading) + 1:] if heading in SECTION_ORDER else ()
    block = f"## {heading}\n\n{line}\n"
    for nxt_heading in later:
        m = re.search(rf"^##\s+{re.escape(nxt_heading)}\s*$", body, re.MULTILINE | re.IGNORECASE)
        if m:
            return body[: m.start()] + block + "\n" + body[m.start():]
    if not body.strip():
        return "\n" + block
    return body.rstrip("\n") + "\n\n" + block


def _load(task_or_path) -> Task:
    return task_or_path if isinstance(task_or_path, Task) else read_task(task_or_path)


def append_progress(task_or_path, text: str, now: datetime | None = None,
                    write: bool = True) -> Task:
    task = _load(task_or_path)
    task.body = append_to_section(task.body, "Progress log", f"- {stamp(now)} — {text}")
    if write:
        write_task_atomic(task)
    return task


def add_note(task_or_path, text: str, now: datetime | None = None, write: bool = True) -> Task:
    """Owner comment. Agents must read the latest one before acting or closing."""
    task = _load(task_or_path)
    task.body = append_to_section(task.body, "Owner notes", f"- {stamp(now)} — {text.strip()}")
    if write:
        write_task_atomic(task)
    return task


def set_status(task_or_path, status: str, evidence: str | None = None,
               note: str | None = None, now: datetime | None = None,
               write: bool = True) -> Task:
    """Change status. `done` requires evidence (argument or already in the file)."""
    status = (status or "").strip().lower()
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; expected one of {', '.join(STATUSES)}")
    task = _load(task_or_path)
    if evidence is not None and str(evidence).strip():
        task.meta["evidence"] = str(evidence).strip()
    if status == "done" and not str(task.get("evidence")).strip():
        raise EvidenceRequired(
            f"{task.id or task.path.name}: cannot set done without evidence "
            "(file path, link or test result)")
    moment = now or datetime.now()
    previous = task.status
    task.meta["status"] = status
    if status in CLOSED_STATUSES:
        task.meta["closed"] = moment.date().isoformat()
        if task.meta.get("lock"):
            task.meta["lock"] = ""
    elif "closed" in task.meta and task.meta.get("closed"):
        task.meta["closed"] = ""
    if previous != status or note:
        line = f"status {previous} -> {status}"
        if note:
            line += f": {note}"
        task.body = append_to_section(task.body, "Progress log", f"- {stamp(moment)} — {line}")
    if write:
        write_task_atomic(task)
    return task


def decide(task_or_path, accepted: bool, note: str = "", now: datetime | None = None,
           write: bool = True) -> Task:
    """Record a human decision. The guard then creates the executing A-task."""
    task = _load(task_or_path)
    if task.s("type") != "decision":
        raise ValueError(f"{task.id or task.path.name} is not a decision (type: decision)")
    moment = now or datetime.now()
    verdict = "accepted" if accepted else "rejected"
    task.meta["decision"] = verdict
    if not str(task.get("evidence")).strip():
        task.meta["evidence"] = f"decision {verdict} by owner on {moment.date().isoformat()}"
    if note:
        add_note(task, f"[{verdict}] {note}", now=moment, write=False)
    return set_status(task, "done", note=f"decision {verdict}", now=moment, write=write)


# ── run-now requests (panel -> runner) ───────────────────────────────────────

def run_now_path(workspace) -> Path:
    return state_dir(workspace) / "run-now.json"


def _read_json_list(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _valid_run_now(entry, now: datetime) -> dict | None:
    if not isinstance(entry, dict):
        return None
    rel, when = entry.get("path"), entry.get("when")
    if not isinstance(rel, str) or not rel.strip() or not isinstance(when, str):
        return None
    try:
        ts = datetime.fromisoformat(when)
    except ValueError:
        return None
    if now - ts > timedelta(minutes=RUN_NOW_TTL_MIN) or ts - now > timedelta(minutes=5):
        return None
    who = entry.get("who") if isinstance(entry.get("who"), str) else ""
    return {"path": rel.strip().replace("\\", "/"), "when": when, "who": who}


def request_run_now(workspace, rel_path: str, who: str = "panel",
                    now: datetime | None = None) -> str:
    """Ask the runner to take this task next. Returns added|duplicate|busy."""
    now = now or datetime.now()
    path = run_now_path(workspace)
    rel = rel_path.replace("\\", "/")
    with file_guard(str(path) + ".lock") as ok:
        if not ok:
            return "busy"
        entries = [e for e in (_valid_run_now(x, now) for x in _read_json_list(path)) if e]
        if any(e["path"].lower() == rel.lower() for e in entries):
            return "duplicate"
        entries.append({"path": rel, "when": now.isoformat(timespec="seconds"), "who": who})
        write_text_atomic(path, json.dumps(entries, indent=2) + "\n")
        return "added"


def take_run_now(workspace, now: datetime | None = None) -> list[dict]:
    """Return and clear valid requests (expired and malformed entries are dropped)."""
    now = now or datetime.now()
    path = run_now_path(workspace)
    if not path.exists():
        return []
    with file_guard(str(path) + ".lock") as ok:
        if not ok:
            return []  # try again next run; never block the queue
        raw = _read_json_list(path)
        entries = [e for e in (_valid_run_now(x, now) for x in raw) if e]
        if raw:
            write_text_atomic(path, "[]\n")
        return entries


# ── logging ──────────────────────────────────────────────────────────────────

def log(workspace, name: str, message: str, max_bytes: int = 1_000_000) -> None:
    """Append a line to .agentos/logs/<name>.log. Never raises."""
    try:
        logs = state_dir(workspace) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        target = logs / f"{name}.log"
        if target.exists() and target.stat().st_size > max_bytes:
            os.replace(target, logs / f"{name}.1.log")  # rotate our own runtime log
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp()} {message}\n")
    except OSError:
        pass


# ── snapshot helpers (dashboard, guard, runner, panel) ───────────────────────

@dataclass
class Snapshot:
    workspace: Path
    projects: dict          # slug -> Task (PROJECT.md) or None
    tasks: list
    errors: list

    def by_id(self, project: str, task_id: str) -> Task | None:
        for task in self.tasks:
            if task.project == project and task.id == task_id:
                return task
        return None

    def project_status(self, slug: str) -> str:
        meta = self.projects.get(slug)
        return (meta.s("status") if meta else "") or "active"

    def wip_limit(self, slug: str, default: int) -> int:
        meta = self.projects.get(slug)
        try:
            value = int(str(meta.get("wip_limit")).strip()) if meta else 0
        except ValueError:
            value = 0
        return value if value > 0 else default


def load_snapshot(workspace) -> Snapshot:
    ws = Path(workspace)
    errors: list = []
    projects = {p.name: read_project(p) for p in iter_project_dirs(ws)}
    tasks = list(iter_tasks(ws, errors=errors))
    return Snapshot(workspace=ws, projects=projects, tasks=tasks, errors=errors)


def is_agent_task(task: Task) -> bool:
    return not task.is_human and task.id.startswith("A-")


def wip_counts(tasks) -> dict:
    """WIP = A-* tasks in todo|in_progress|blocked, per project (inbox excluded)."""
    counts: dict = {}
    for task in tasks:
        if task.project and is_agent_task(task) and task.status in OPEN_STATUSES:
            counts[task.project] = counts.get(task.project, 0) + 1
    return counts
