"""``python -m agentos doctor`` - diagnose an installation without changing anything.

Checks (level: ok | info | warn | fail):
  python        interpreter version >= 3.11
  claude        `claude` CLI in PATH and its version
  workspace     workspace found, agentos.toml parses and has valid values
  layout        expected workspace folders exist
  profile       the queue permission profile file exists and is valid JSON
  schedule      periodic job state matches [queue].enabled
  secrets       .env is not tracked by git (workspace and engine repo)
  gitleaks      secret scanner available (optional)
  banned words  private words from <workspace>/.agentos/banned_words.txt found in .claude/ (warning)

Exit code 1 if any check fails.

The banned-word matcher is shared with the repo's clean-repo test. It is token based (so a
short word never matches inside a longer one) and accepts plain phrases or ``sha256:<hex>``
entries, so a private list can be published without revealing its contents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
MIN_PYTHON = (3, 11)
PROFILES = ("safe", "developer", "full")
NOTIFY_KINDS = ("none", "file", "telegram")
MAX_NGRAM = 4
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache"}

LEVEL_ORDER = {"ok": 0, "info": 1, "warn": 2, "fail": 3}


@dataclass
class Check:
    name: str
    level: str
    message: str


# --------------------------------------------------------------------------- matcher
_EXTRA_FOLD = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "ß": "ss"})


def normalize_tokens(text: str) -> list:
    """Lower-case, strip accents, split on anything that is not a letter or digit."""
    text = unicodedata.normalize("NFKD", text.translate(_EXTRA_FOLD))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.findall(r"[a-z0-9]+", text)


def phrase_key(phrase: str) -> str:
    return " ".join(normalize_tokens(phrase))


def phrase_hash(phrase: str) -> str:
    return "sha256:" + hashlib.sha256(phrase_key(phrase).encode("utf-8")).hexdigest()


def load_banned(path: Path) -> tuple:
    """Return (plain_keys: set, hashes: set). Lines: phrase | sha256:<hex>; '#' starts a comment."""
    plain, hashes = set(), set()
    if not Path(path).exists():
        return plain, hashes
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.lower().startswith("sha256:"):
            hashes.add(line.lower())
        else:
            key = phrase_key(line)
            if key:
                plain.add(key)
    return plain, hashes


def find_banned(text: str, plain: set, hashes: set, max_n: int = MAX_NGRAM) -> set:
    """Return the set of matched n-gram keys (or their hashes for hashed entries)."""
    tokens = normalize_tokens(text)
    hits = set()
    for n in range(1, max_n + 1):
        for i in range(len(tokens) - n + 1):
            key = " ".join(tokens[i:i + n])
            if key in plain:
                hits.add(key)
            if hashes:
                h = "sha256:" + hashlib.sha256(key.encode("utf-8")).hexdigest()
                if h in hashes:
                    hits.add(h)
    return hits


def iter_text_files(root: Path, skip_dirs: Iterable[str] = SKIP_DIRS) -> Iterable[Path]:
    skip = set(skip_dirs)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                head = p.read_bytes()[:8192]
            except OSError:
                continue
            if b"\x00" in head:
                continue
            yield p


# --------------------------------------------------------------------------- helpers
def _load_toml(path: Path):
    import tomllib

    return tomllib.loads(path.read_text(encoding="utf-8"))


def find_workspace(start: Optional[Path] = None) -> Optional[Path]:
    cur = Path(start or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / "agentos.toml").exists():
            return p
    return None


def _run(runner, argv, cwd=None, timeout=20):
    try:
        return runner(argv, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


# --------------------------------------------------------------------------- checks
def check_python(version=None) -> Check:
    v = tuple(version or sys.version_info[:3])
    shown = ".".join(str(x) for x in v[:3])
    if v[:2] >= MIN_PYTHON:
        return Check("python", "ok", f"Python {shown} ({sys.executable})")
    return Check("python", "fail", f"Python {shown} - need 3.11 or newer")


def check_claude(claude_bin: str, which, runner) -> Check:
    path = which(claude_bin)
    if not path:
        return Check("claude", "fail", f"'{claude_bin}' not found in PATH - install Claude Code CLI")
    res = _run(runner, [path, "--version"])
    ver = (res.stdout or "").strip().splitlines()[0] if res.returncode == 0 and res.stdout else "version unknown"
    return Check("claude", "ok", f"{ver} ({path})")


def check_engine(ws: Path, runner) -> Check:
    """The workspace venv that every generated command uses (see agentos/env.py)."""
    from agentos import env as engine_env

    py = engine_env.venv_python(ws)
    if not py.is_file():
        return Check("engine", "info", "no .agentos/venv - run engine commands from the repo folder or with "
                     "the repo on PYTHONPATH; re-run install.py to create the venv")
    res = _run(runner, [str(py), "-P", "-c", "import agentos; print(agentos.__file__)"], cwd=ws)
    if res.returncode != 0:
        return Check("engine", "fail", f"{py} cannot import agentos - re-run install.py")
    where = Path((res.stdout or "").strip().splitlines()[-1] if res.stdout else "")
    try:
        inside = where.resolve().is_relative_to(engine_env.venv_dir(ws).resolve())
    except (OSError, ValueError):
        inside = False
    if inside:
        return Check("engine", "ok", f"installed in .agentos/venv ({engine_env.engine_command()})")
    return Check("engine", "warn", f"linked to {where.parent.parent} (offline fallback) - re-run install.py "
                 "online for a normal install")


def validate_config(cfg: dict) -> list:
    problems = []
    if not str(cfg.get("owner_name", "")).strip():
        problems.append("owner_name is empty")
    if not str(cfg.get("language", "")).strip():
        problems.append("language is empty")
    q = cfg.get("queue", {})
    if not isinstance(q, dict):
        problems.append("[queue] must be a table")
        q = {}
    if q.get("profile", "safe") not in PROFILES:
        problems.append(f"queue.profile must be one of {PROFILES}")
    for key in ("interval_minutes", "timeout_minutes", "max_tasks_per_run"):
        val = q.get(key, 1)
        if not isinstance(val, int) or isinstance(val, bool) or val < 1:
            problems.append(f"queue.{key} must be a positive integer")
    n = cfg.get("notify", {})
    if isinstance(n, dict) and n.get("kind", "none") not in NOTIFY_KINDS:
        problems.append(f"notify.kind must be one of {NOTIFY_KINDS}")
    p = cfg.get("panel", {})
    if isinstance(p, dict) and "port" in p and not (isinstance(p["port"], int) and 0 < p["port"] < 65536):
        problems.append("panel.port must be 1-65535")
    pr = cfg.get("projects", {})
    if isinstance(pr, dict) and "wip_limit" in pr and not (isinstance(pr["wip_limit"], int) and pr["wip_limit"] > 0):
        problems.append("projects.wip_limit must be a positive integer")
    return problems


def _env_has_key(ws: Path, key: str) -> bool:
    if os.environ.get(key):
        return True
    env = ws / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith(key + "=") and line.split("=", 1)[1].strip():
                return True
    return False


def check_env_tracked(directory: Path, which, runner, label: str) -> Optional[Check]:
    env = directory / ".env"
    if not env.exists() or not which("git"):
        return None
    inside = _run(runner, ["git", "rev-parse", "--is-inside-work-tree"], cwd=directory)
    if inside.returncode != 0:
        return None
    tracked = _run(runner, ["git", "ls-files", "--error-unmatch", ".env"], cwd=directory)
    if tracked.returncode == 0:
        return Check("secrets", "fail", f"{label}/.env is tracked by git - remove it from the index and rotate its secrets")
    ignored = _run(runner, ["git", "check-ignore", "-q", ".env"], cwd=directory)
    if ignored.returncode != 0:
        return Check("secrets", "warn", f"{label}/.env is not in .gitignore")
    return Check("secrets", "ok", f"{label}/.env is ignored by git")


def check_banned_words(ws: Path) -> Check:
    list_path = ws / ".agentos" / "banned_words.txt"
    if not list_path.exists():
        return Check("banned words", "info", "no .agentos/banned_words.txt (optional private word list)")
    plain, hashes = load_banned(list_path)
    claude_dir = ws / ".claude"
    hits = {}
    if claude_dir.exists():
        for f in iter_text_files(claude_dir):
            found = find_banned(f.read_text(encoding="utf-8", errors="replace"), plain, hashes)
            if found:
                hits[str(f.relative_to(ws))] = len(found)
    if hits:
        files = ", ".join(sorted(hits)[:5]) + (" ..." if len(hits) > 5 else "")
        return Check("banned words", "warn", f"private words found in {len(hits)} file(s): {files}")
    return Check("banned words", "ok", ".claude/ is free of listed private words")


def run_checks(
    workspace: Optional[Path] = None,
    *,
    which: Callable = shutil.which,
    runner: Callable = subprocess.run,
    schedule_status: Optional[Callable] = None,
) -> list:
    checks = [check_python()]
    ws = Path(workspace).resolve() if workspace else find_workspace()
    cfg: dict = {}

    if ws is None or not (ws / "agentos.toml").exists():
        checks.append(check_claude("claude", which, runner))
        checks.append(Check("workspace", "fail", "no agentos.toml found - run install.py or pass --workspace"))
        return checks

    try:
        cfg = _load_toml(ws / "agentos.toml")
        problems = validate_config(cfg)
        if problems:
            checks.append(Check("workspace", "fail", f"{ws}: " + "; ".join(problems)))
        else:
            checks.append(Check("workspace", "ok", str(ws)))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("workspace", "fail", f"agentos.toml does not parse: {exc}"))

    queue = cfg.get("queue", {}) if isinstance(cfg.get("queue"), dict) else {}
    checks.append(check_claude(str(queue.get("claude_bin", "claude") or "claude"), which, runner))

    missing = [d for d in ("projects", "inbox", ".claude") if not (ws / d).is_dir()]
    checks.append(Check("layout", "warn", "missing: " + ", ".join(missing)) if missing
                  else Check("layout", "ok", "projects/, inbox/, .claude/ present"))

    checks.append(check_engine(ws, runner))

    profile = queue.get("profile", "safe")
    from agentos import env as engine_env

    prof_path = engine_env.profiles_dir() / f"{profile}.json"
    if not prof_path.exists():
        checks.append(Check("profile", "fail", f"profile file missing: profiles/{profile}.json"))
    else:
        try:
            json.loads(prof_path.read_text(encoding="utf-8"))
            level = "warn" if profile == "full" else "ok"
            note = " (full profile: no permission prompts - see SECURITY.md)" if profile == "full" else ""
            checks.append(Check("profile", level, f"profiles/{profile}.json{note}"))
        except ValueError as exc:
            checks.append(Check("profile", "fail", f"profiles/{profile}.json is not valid JSON: {exc}"))

    # schedule
    try:
        if schedule_status is None:
            from agentos import scheduler

            schedule_status = scheduler.status
        st = schedule_status(ws)
        installed = bool(st.get("installed"))
        enabled = bool(queue.get("enabled", False))
        if enabled and not installed:
            checks.append(Check("schedule", "warn", "queue enabled but no scheduled job - run `python -m agentos schedule install`"))
        elif not enabled and installed:
            checks.append(Check("schedule", "warn", f"queue disabled but job {st.get('name')} is installed"))
        elif installed:
            state = st.get("state") or {}
            stale = [k for k in ("python", "launcher") if state.get(k) and not Path(state[k]).exists()]
            if stale:
                checks.append(Check("schedule", "fail", f"job {st.get('name')} points to missing {', '.join(stale)} - reinstall"))
            else:
                checks.append(Check("schedule", "ok", f"{st.get('backend')}: {st.get('name')}"))
        else:
            checks.append(Check("schedule", "info", "queue disabled, no scheduled job"))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("schedule", "warn", f"could not read schedule status: {exc}"))

    notify = cfg.get("notify", {}) if isinstance(cfg.get("notify"), dict) else {}
    if notify.get("kind") == "telegram":
        ok = _env_has_key(ws, "AGENTOS_TELEGRAM_TOKEN") and _env_has_key(ws, "AGENTOS_TELEGRAM_CHAT_ID")
        checks.append(Check("notify", "ok" if ok else "warn",
                            "telegram credentials present in .env" if ok
                            else "notify.kind=telegram but AGENTOS_TELEGRAM_TOKEN / AGENTOS_TELEGRAM_CHAT_ID missing in .env"))

    for directory, label in ((ws, "workspace"), (REPO_ROOT, "engine")):
        c = check_env_tracked(directory, which, runner, label)
        if c:
            checks.append(c)

    checks.append(Check("gitleaks", "ok", f"available ({which('gitleaks')})") if which("gitleaks")
                  else Check("gitleaks", "info", "not installed (optional secret scanner: https://github.com/gitleaks/gitleaks)"))

    checks.append(check_banned_words(ws))
    return checks


def worst(checks: list) -> str:
    return max((c.level for c in checks), key=lambda l: LEVEL_ORDER[l], default="ok")


def render(checks: list) -> str:
    width = max((len(c.name) for c in checks), default=8)
    return "\n".join(f"[{c.level.upper():4}] {c.name.ljust(width)}  {c.message}" for c in checks)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="agentos doctor", description="Diagnose the installation.")
    ap.add_argument("--workspace", type=Path, default=None)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    checks = run_checks(args.workspace)
    if args.json:
        print(json.dumps([c.__dict__ for c in checks], indent=2))
    else:
        print(render(checks))
    return 1 if worst(checks) == "fail" else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
