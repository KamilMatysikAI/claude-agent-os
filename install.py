#!/usr/bin/env python3
"""claude-agent-os installer.

    python install.py                          interactive wizard
    python install.py --non-interactive --workspace PATH [--owner NAME] [--language en]
                      [--timezone UTC] [--profile safe|developer|full] [--queue|--no-queue]
                      [--interval 30] [--panel|--no-panel] [--notify none|file|telegram]
                      [--with-demo] [--rules web,sales] [--no-schedule] [--schedule-print-only]
                      [--no-venv]
                      [--confirm-full "I understand"]
    python install.py uninstall --workspace PATH [--print-only]

Guarantees:
* never overwrites an existing file - a differing file is written next to it as ``<file>.new``
  and listed in the report;
* idempotent - running it twice with the same answers leaves the workspace unchanged;
* ``uninstall`` removes only the scheduled job and engine-owned runtime files, never user data.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import platform
import shutil
import sys
from pathlib import Path

MIN_PYTHON = (3, 11)
if sys.version_info < MIN_PYTHON:  # keep this file importable by old interpreters for this message
    sys.stderr.write("claude-agent-os needs Python 3.11 or newer (found %s).\n" % platform.python_version())
    sys.exit(1)

import tomllib  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from agentos import PRODUCT_NAME  # type: ignore
except Exception:  # engine package not importable yet
    PRODUCT_NAME = "claude-agent-os"

TEMPLATE_DIR = REPO_ROOT / "template"
DEMO_DIR = REPO_ROOT / "demo"
DEMO_DIRS = {"pl": REPO_ROOT / "demo-pl"}  # demo per language; anything else gets demo/


def demo_dir_for(language) -> Path:
    """The demo in the user's language when the package has one ("pl", "pl-PL"), else English."""
    lang = str(language or "").strip().lower()[:2]
    candidate = DEMO_DIRS.get(lang)
    return candidate if candidate is not None and candidate.is_dir() else DEMO_DIR
FULL_CONFIRMATION = "I understand"
PROFILES = ("safe", "developer", "full")
NOTIFY_KINDS = ("none", "file", "telegram")
SKIP_NAMES = {"__pycache__", ".DS_Store", "Thumbs.db"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
RUNTIME_SUBDIRS = ("logs", "locks", "tmp")
# Optional rule packs. Claude Code auto-loads everything under .claude/rules/ (subfolders
# too), so they live outside it in the package and are copied in only when chosen.
OPTIONAL_RULES_DIR = ".claude/rules-optional"
# Never copied from the package: archived rules (kept outside the auto-loaded dir on purpose)
# and engine runtime state such as .agentos/tmp/.
NEVER_COPY_PREFIXES = (".claude/rules-archive/", ".agentos/")
WORKSPACE_DIRS = ("projects", "inbox/done", "ideas", "notes/sessions")
# Seed files: written once, then owned by the user, /setup or the engine (dashboard, guard).
# A re-run never reports them as conflicts.
CREATE_ONLY = {"TODO.md", ".claude/rules/persona.md", ".claude/rules/soul.md", ".claude/rules/context.md"}


def is_create_only(rel: str, from_demo: bool) -> bool:
    if from_demo or rel in CREATE_ONLY:
        return True
    return rel.startswith("projects/") and not rel.startswith("projects/.templates/")
# Engine-owned runtime files that `uninstall` may remove. Everything else stays.
RUNTIME_REMOVABLE = ("tick.py", "install.json", "schedule.json", "run-now.json")

DEFAULT_GITIGNORE = """\
# claude-agent-os runtime state and secrets
.agentos/
.env
.env.*
*.new
"""

PROFILE_HELP = {
    "safe": "read/write files inside the workspace, web search; no shell, secrets denied (recommended)",
    "developer": "safe + read-only git and test runners; no push, no rm, no curl",
    "full": "NO permission prompts at all (--dangerously-skip-permissions) - only if you know why",
}

FULL_WARNING = """
  !! The 'full' profile runs `claude -p` with --dangerously-skip-permissions.
  !! The agent can then run any shell command as your user, unattended, on a schedule.
  !! Secret files stay on the deny list, but nothing else is stopped. Tasks from external
  !! sources are still forced to 'safe'. Read SECURITY.md before you continue.
"""


class InstallError(Exception):
    pass


# --------------------------------------------------------------------------- answers
def defaults_from_existing(workspace: Path) -> dict:
    cfg_path = workspace / "agentos.toml"
    if not cfg_path.exists():
        return {}
    try:
        cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    q = cfg.get("queue", {}) if isinstance(cfg.get("queue"), dict) else {}
    n = cfg.get("notify", {}) if isinstance(cfg.get("notify"), dict) else {}
    p = cfg.get("panel", {}) if isinstance(cfg.get("panel"), dict) else {}
    out = {
        "owner": cfg.get("owner_name"),
        "language": cfg.get("language"),
        "timezone": cfg.get("timezone"),
        "profile": q.get("profile"),
        "queue": q.get("enabled"),
        "interval": q.get("interval_minutes"),
        "panel": p.get("enabled"),
        "notify": n.get("kind"),
    }
    return {k: v for k, v in out.items() if v is not None}


BASE_DEFAULTS = {
    "owner": "Owner",
    "language": "en",
    "timezone": "UTC",
    "profile": "safe",
    "queue": False,
    "interval": 30,
    "panel": False,
    "notify": "none",
}


def resolve_answers(args: argparse.Namespace, existing: dict) -> dict:
    ans = dict(BASE_DEFAULTS)
    ans.update(existing)
    for key in BASE_DEFAULTS:
        val = getattr(args, key, None)
        if val is not None:
            ans[key] = val
    return ans


def validate_answers(ans: dict) -> None:
    if not str(ans["owner"]).strip():
        raise InstallError("owner name must not be empty")
    if ans["profile"] not in PROFILES:
        raise InstallError(f"profile must be one of {PROFILES}")
    if ans["notify"] not in NOTIFY_KINDS:
        raise InstallError(f"notify must be one of {NOTIFY_KINDS}")
    try:
        ans["interval"] = int(ans["interval"])
    except (TypeError, ValueError):
        raise InstallError("interval must be a whole number of minutes")
    if not 1 <= ans["interval"] <= 1439:
        raise InstallError("interval must be between 1 and 1439 minutes")


def _ask(prompt: str, default, input_fn=input) -> str:
    shown = "yes" if default is True else "no" if default is False else default
    raw = input_fn(f"{prompt} [{shown}]: ").strip()
    return raw if raw else str(shown)


def _ask_bool(prompt: str, default: bool, input_fn=input) -> bool:
    while True:
        raw = _ask(prompt, default, input_fn).lower()
        if raw in ("y", "yes", "t", "true", "1"):
            return True
        if raw in ("n", "no", "f", "false", "0"):
            return False
        print("  please answer yes or no")


def _ask_choice(prompt: str, choices, default: str, input_fn=input) -> str:
    while True:
        raw = _ask(f"{prompt} ({'/'.join(choices)})", default, input_fn).lower()
        if raw in choices:
            return raw
        print(f"  choose one of: {', '.join(choices)}")


def confirm_full(input_fn=input) -> bool:
    print(FULL_WARNING)
    typed = input_fn(f'  Type "{FULL_CONFIRMATION}" to enable the full profile: ').strip()
    return typed == FULL_CONFIRMATION


def wizard(args: argparse.Namespace, input_fn=input) -> dict:
    """Interactive questions. Returns answers incl. workspace."""
    print(f"\n{PRODUCT_NAME} installer\n")
    ws_default = str(args.workspace or (Path.home() / "agent-workspace"))
    workspace = Path(_ask("Workspace folder (new or existing)", ws_default, input_fn)).expanduser()
    ans = resolve_answers(args, defaults_from_existing(workspace))
    ans["owner"] = _ask("Your first name (used in agent texts)", ans["owner"], input_fn)
    ans["language"] = _ask("Language agents write to you in (e.g. en, de, pl)", ans["language"], input_fn)
    ans["timezone"] = _ask("Time zone (IANA, e.g. Europe/Berlin)", ans["timezone"], input_fn)
    ans["queue"] = _ask_bool("Run the agent queue on a schedule?", bool(ans["queue"]), input_fn)
    if ans["queue"]:
        print("  Queue permission profiles:")
        for name in PROFILES:
            print(f"    {name:9} {PROFILE_HELP[name]}")
        while True:
            ans["profile"] = _ask_choice("Queue profile", PROFILES, ans["profile"], input_fn)
            if ans["profile"] != "full" or confirm_full(input_fn):
                break
            print("  Not confirmed - choose another profile.")
            ans["profile"] = "safe"
        ans["interval"] = _ask("Run every N minutes", ans["interval"], input_fn)
    ans["panel"] = _ask_bool("Enable the local web panel (127.0.0.1)?", bool(ans["panel"]), input_fn)
    ans["notify"] = _ask_choice("Notifications", NOTIFY_KINDS, ans["notify"], input_fn)
    optional = available_optional_rules(TEMPLATE_DIR)
    if optional:
        enabled = [r for r in optional if (workspace / ".claude" / "rules" / f"{r}.md").exists()]
        default_rules = ",".join(parse_rules(args.rules) or enabled) or "none"
        while True:
            raw = _ask(f"Optional rule packs to enable ({', '.join(optional)}; comma separated)", default_rules, input_fn)
            picked = parse_rules(raw)
            bad = [r for r in picked if r not in optional]
            if not bad:
                break
            print(f"  unknown: {', '.join(bad)}")
        ans["rules"] = picked
    ans["with_demo"] = _ask_bool("Copy the demo project?", bool(args.with_demo), input_fn)
    ans["workspace"] = workspace
    ans["full_confirmed"] = ans["profile"] == "full"
    return ans


# --------------------------------------------------------------------------- rendering
def _toml_str(s: str) -> str:
    return json.dumps(str(s), ensure_ascii=False)  # JSON string escaping is valid TOML basic string


def render_config(ans: dict) -> str:
    return f"""# {PRODUCT_NAME} configuration. Secrets never go here - use .env.
owner_name = {_toml_str(ans['owner'])}
language = {_toml_str(ans['language'])}              # language agents write in for the user
timezone = {_toml_str(ans['timezone'])}

[queue]
enabled = {str(bool(ans['queue'])).lower()}
profile = {_toml_str(ans['profile'])}              # safe|developer|full (max allowed; external sources always safe)
interval_minutes = {int(ans['interval'])}
timeout_minutes = 45
max_tasks_per_run = 1
claude_bin = "claude"
model = ""                   # empty = CLI default
cooldown_minutes = 0

[projects]
wip_limit = 5
human_task_max_minutes = 15

[notify]
kind = {_toml_str(ans['notify'])}                # none|file|telegram
digest_hours = [8, 15, 21]   # effects only, batched; failures go to log + one daily line
# telegram token/chat id ONLY from .env: AGENTOS_TELEGRAM_TOKEN, AGENTOS_TELEGRAM_CHAT_ID

[panel]
enabled = {str(bool(ans['panel'])).lower()}
host = "127.0.0.1"
port = 8777
"""


def engine_placeholder(workspace: Path) -> str:
    """`{{engine}}` in templates: the workspace venv command when the venv exists."""
    from agentos import env as engine_env

    return engine_env.engine_command(venv=engine_env.has_venv(workspace))


def placeholders(ans: dict, workspace: Path) -> dict:
    return {
        "engine": engine_placeholder(workspace),
        "owner_name": str(ans["owner"]),
        "language": str(ans["language"]),
        "timezone": str(ans["timezone"]),
        "workspace": str(workspace),
        "workspace_name": workspace.name,
        "queue_profile": str(ans["profile"]),
        "product_name": PRODUCT_NAME,
        "date": _dt.date.today().isoformat(),
    }


def fill(text: str, values: dict) -> str:
    for key, val in values.items():
        text = text.replace("{{" + key + "}}", val).replace("{{ " + key + " }}", val)
    return text


# --------------------------------------------------------------------------- file ops
class Report:
    def __init__(self):
        self.created, self.unchanged, self.conflicts, self.notes, self.kept = [], [], [], [], []

    def summary(self) -> str:
        lines = [f"created: {len(self.created)}, unchanged: {len(self.unchanged)}, conflicts: {len(self.conflicts)}, "
                 f"kept (already yours): {len(self.kept)}"]
        for target, new in self.conflicts:
            lines.append(f"  conflict: {target} exists and differs -> new version saved as {new.name}")
        lines += [f"  note: {n}" for n in self.notes]
        return "\n".join(lines)


def place_file(target: Path, data: bytes, report: Report, create_only: bool = False) -> None:
    """Write ``data`` to ``target`` without ever overwriting an existing, different file."""
    if target.exists():
        if target.is_file() and target.read_bytes() == data:
            report.unchanged.append(target)
            return
        if create_only:
            report.kept.append(target)
            return
        new = target.with_name(target.name + ".new")
        if not (new.exists() and new.read_bytes() == data):
            if new.exists() and not new.is_file():
                report.notes.append(f"cannot write {new}: a directory with that name exists")
                return
            new.parent.mkdir(parents=True, exist_ok=True)
            new.write_bytes(data)
        report.conflicts.append((target, new))
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    report.created.append(target)


def _render_bytes(src: Path, values: dict) -> bytes:
    raw = src.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw  # binary asset - copy as is
    return fill(text, values).encode("utf-8")


def collect_sources(src_root: Path, skip_top=()) -> dict:
    """Map relative path -> source file for one package folder."""
    found = {}
    if not src_root.is_dir():
        return found
    for dirpath, dirnames, filenames in os.walk(src_root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_NAMES)
        rel_dir = Path(dirpath).relative_to(src_root)
        for fn in sorted(filenames):
            if fn in SKIP_NAMES or Path(fn).suffix in SKIP_SUFFIXES:
                continue
            if rel_dir == Path(".") and fn in skip_top:
                continue
            rel = (rel_dir / fn).as_posix()
            if rel.startswith(NEVER_COPY_PREFIXES):
                continue
            found[rel] = Path(dirpath) / fn
    return found


def copy_sources(sources: dict, dst_root: Path, values: dict, report: Report, demo_root=None) -> None:
    for rel in sorted(sources):
        src = sources[rel]
        from_demo = demo_root is not None and Path(demo_root) in src.parents
        place_file(dst_root / rel, _render_bytes(src, values), report,
                   create_only=is_create_only(rel, from_demo))


def available_optional_rules(template_dir: Path) -> list:
    d = Path(template_dir) / OPTIONAL_RULES_DIR
    return sorted(p.stem for p in d.glob("*.md")) if d.is_dir() else []


def parse_rules(value) -> list:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = str(value).replace(";", ",").split(",")
    out = []
    for item in items:
        name = str(item).strip().lower()
        if name.endswith(".md"):
            name = name[:-3]
        if name and name not in ("none", "no", "-") and name not in out:
            out.append(name)
    return out


def _previous_manifest(workspace: Path) -> dict:
    path = workspace / ".agentos" / "install.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        return {}


def write_manifest(workspace: Path, ans: dict, claude_path, report: Report) -> None:
    path = workspace / ".agentos" / "install.json"
    previous = {}
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            previous = {}
    data = {
        "product": PRODUCT_NAME,
        "repo": str(REPO_ROOT),
        "python": sys.executable,
        "claude": claude_path or "",
        "installed_at": previous.get("installed_at") or _dt.datetime.now().isoformat(timespec="seconds"),
        "with_demo": bool(ans.get("with_demo")) or bool(previous.get("with_demo")),
    }
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8", newline="\n")  # engine-owned file, not user data


# --------------------------------------------------------------------------- engine venv
# Package sources copied to a temp dir for `pip install`, so the build never writes
# build/ or *.egg-info into the cloned repo. Paths are relative to REPO_ROOT.
PACKAGE_SOURCES = ("pyproject.toml", "agentos", "panel", "profiles", "template/ideas/.templates",
                   "template/.claude/skills/add-idea/scripts")


def _sub(argv, cwd=None, timeout=600) -> "subprocess.CompletedProcess":
    import subprocess

    try:
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, errors="replace",
                              timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def _last_line(res) -> str:
    text = ((res.stderr or "") + "\n" + (res.stdout or "")).strip().splitlines()
    return text[-1][:300] if text else f"exit code {res.returncode}"


def _staged_sources(dst: Path) -> Path:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "build", "*.egg-info")
    for rel in PACKAGE_SOURCES:
        src = REPO_ROOT / rel
        if src.is_dir():
            shutil.copytree(src, dst / rel, ignore=ignore)
        elif src.is_file():
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst / rel)
    return dst


def setup_engine(workspace: Path, out=print, pip_args=()) -> dict:
    """Create (or reuse) <workspace>/.agentos/venv and install the engine into it.

    Normal install from a staged copy of the package (never editable). If pip cannot build
    it (offline, no pip), link the repo with a .pth file instead and say so. Never raises:
    the workspace files are installed either way.
    """
    import tempfile
    import venv

    from agentos import env as engine_env

    vdir = engine_env.venv_dir(workspace)
    py = engine_env.venv_python(workspace)
    result = {"mode": "none", "python": "", "message": ""}
    if not py.is_file():
        out(f"engine: creating {vdir} ...")
        for with_pip in (True, False):
            try:
                venv.EnvBuilder(with_pip=with_pip, clear=False).create(str(vdir))
            except Exception as exc:  # noqa: BLE001 - try without pip, then give up
                result["message"] = f"venv failed ({'with' if with_pip else 'without'} pip): {exc}"
                continue
            if py.is_file():
                break
    if not py.is_file():
        result["message"] = (result["message"] or "venv was not created") + \
            " - engine commands run from the repo folder (PYTHONPATH) instead"
        return result
    result["python"] = str(py)

    purelib = _sub([str(py), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"])
    site = Path(purelib.stdout.strip()) if purelib.returncode == 0 and purelib.stdout.strip() else None
    link = site / engine_env.LINK_FILE if site else None

    has_pip = _sub([str(py), "-m", "pip", "--version"]).returncode == 0
    failure = "pip is not available in the venv"
    if has_pip:
        out("engine: pip install (normal, not editable) ...")
        with tempfile.TemporaryDirectory(prefix="agentos-build-") as tmp:
            src = _staged_sources(Path(tmp) / "src")
            base = [str(py), "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
                    "--quiet", "--force-reinstall", "--no-deps", *pip_args]
            res = _sub(base + [str(src)], cwd=tmp)
            if res.returncode != 0:  # offline: try the setuptools already in the venv, if any
                res = _sub(base + ["--no-build-isolation", str(src)], cwd=tmp)
        if res.returncode == 0:
            if link and link.exists():
                link.unlink()  # engine-owned file from an earlier offline install
            result["mode"] = "installed"
        else:
            failure = f"pip install failed: {_last_line(res)}"
    if result["mode"] != "installed":
        if not link:
            result["message"] = f"{failure}; cannot find the venv site-packages"
            return result
        link.write_text(str(REPO_ROOT) + "\n", encoding="utf-8")
        result["mode"] = "linked"
        result["message"] = (f"{failure}. Linked the repo folder into the venv instead (works offline; "
                             f"the engine then runs from {REPO_ROOT}). Re-run install.py when online "
                             "for a normal install.")
    check = _sub([str(py), "-P", "-c", "import agentos, panel; print(agentos.__file__)"],
                 cwd=str(workspace))
    if check.returncode != 0:
        result["mode"] = "broken"
        result["message"] = f"the venv cannot import the engine: {_last_line(check)}"
    return result


# --------------------------------------------------------------------------- install
def install(ans: dict, *, schedule: bool = True, schedule_print_only: bool = False,
            run_doctor: bool = True, out=print, template_dir=None,
            demo_dir=None, create_venv: bool = False) -> Report:
    template_dir = Path(template_dir) if template_dir else TEMPLATE_DIR
    demo_dir = Path(demo_dir) if demo_dir else demo_dir_for(ans.get("language"))
    workspace = Path(ans["workspace"]).expanduser().resolve()
    validate_answers(ans)
    if ans["profile"] == "full" and not ans.get("full_confirmed"):
        raise InstallError(f'profile "full" requires confirmation: --confirm-full "{FULL_CONFIRMATION}"')
    if workspace.exists() and not workspace.is_dir():
        raise InstallError(f"{workspace} exists and is not a folder")

    out(f"OS: {platform.system()} {platform.release()} | Python {platform.python_version()} ({sys.executable})")
    claude_path = shutil.which("claude")
    out(f"claude CLI: {claude_path or 'NOT FOUND - install Claude Code before enabling the queue'}")

    report = Report()
    workspace.mkdir(parents=True, exist_ok=True)
    engine = {"mode": "skipped", "message": ""}
    if create_venv:
        engine = setup_engine(workspace, out=out)
        if engine["mode"] == "installed":
            report.notes.append(f"engine installed in {workspace / '.agentos' / 'venv'}")
        elif engine["mode"] == "linked":
            report.notes.append("engine NOT installed by pip - " + engine["message"])
        else:
            report.notes.append("engine venv not available - " + engine["message"])
    values = placeholders(ans, workspace)

    # Demo is sticky: once installed with the demo, re-runs keep overlaying it (idempotency).
    if _previous_manifest(workspace).get("with_demo"):
        ans["with_demo"] = True
    sources = {rel: src for rel, src in collect_sources(template_dir).items()
               if not rel.startswith(OPTIONAL_RULES_DIR + "/")}
    chosen = parse_rules(ans.get("rules"))
    available = available_optional_rules(template_dir)
    unknown = [r for r in chosen if r not in available]
    if unknown:
        raise InstallError(f"unknown optional rules: {', '.join(unknown)} (available: {', '.join(available) or 'none'})")
    for name in chosen:
        sources[f".claude/rules/{name}.md"] = template_dir / OPTIONAL_RULES_DIR / f"{name}.md"
    if not sources:
        report.notes.append(f"{template_dir.name}/ not found or empty in the package - only config written")
    if ans.get("with_demo"):
        if not demo_dir.is_dir():
            report.notes.append("demo/ not found in the package - skipped")
        # demo files overlay template files with the same path; the installer owns agentos.toml
        sources.update(collect_sources(demo_dir, skip_top=("README.md", "agentos.toml")))
    copy_sources(sources, workspace, values, report, demo_root=demo_dir if ans.get("with_demo") else None)

    for d in WORKSPACE_DIRS:
        (workspace / d).mkdir(parents=True, exist_ok=True)
    for d in RUNTIME_SUBDIRS:
        (workspace / ".agentos" / d).mkdir(parents=True, exist_ok=True)

    place_file(workspace / "agentos.toml", render_config(ans).encode("utf-8"), report)

    gi = workspace / ".gitignore"
    if not gi.exists():
        place_file(gi, DEFAULT_GITIGNORE.encode("utf-8"), report)
    else:
        content = gi.read_text(encoding="utf-8", errors="replace")
        covered = content.split()
        missing = [p for p in (".agentos/", ".env") if p not in covered]
        if ".agentos/" in missing and ".agentos/tmp/" in covered:
            missing.remove(".agentos/")  # runtime tmp at least is ignored
        if missing:
            report.notes.append(f".gitignore does not list {', '.join(missing)} - add it so runtime state and secrets stay out of git")

    write_manifest(workspace, ans, claude_path, report)

    if ans["notify"] == "telegram":
        report.notes.append("telegram: put AGENTOS_TELEGRAM_TOKEN and AGENTOS_TELEGRAM_CHAT_ID in .env (never in agentos.toml)")
    if any(t.name == "agentos.toml" for t, _ in report.conflicts):
        report.notes.append("agentos.toml already existed with other values - review agentos.toml.new; the old config is still active")

    # schedule follows the *active* config, so a conflict never silently changes behaviour
    active_cfg = tomllib.loads((workspace / "agentos.toml").read_text(encoding="utf-8"))
    queue = active_cfg.get("queue", {})
    if schedule and queue.get("enabled"):
        try:
            from agentos import scheduler

            scheduler.install(workspace, queue.get("interval_minutes", 30),
                              print_only=schedule_print_only, out=out)
            report.notes.append("scheduled job " + ("printed (not installed)" if schedule_print_only else "installed"))
        except Exception as exc:  # noqa: BLE001 - the files are in place; report and continue
            report.notes.append(f"schedule NOT installed: {exc}")
    elif queue.get("enabled"):
        report.notes.append("queue enabled but schedule skipped (--no-schedule); run `python -m agentos schedule install` later")

    out("\n" + report.summary())
    out("\n" + next_steps(workspace, active_cfg))

    if run_doctor:
        try:
            from agentos import doctor

            out("\nDoctor:")
            out(doctor.render(doctor.run_checks(workspace)))
        except Exception as exc:  # noqa: BLE001
            out(f"doctor not available: {exc}")
    return report


def next_steps(workspace: Path, cfg: dict) -> str:
    """What to type next, with the real paths. With the workspace venv every engine command
    runs from the workspace root; without it (--no-venv, or venv creation failed) from the
    repo folder, or anywhere with the repo on PYTHONPATH."""
    from agentos import env as engine_env

    panel = cfg.get("panel", {}) if isinstance(cfg.get("panel"), dict) else {}
    lines = ["Next steps:", f'  cd "{workspace}"', "  claude                  then /setup and /new-project", ""]
    port_hint = ""
    if panel.get("enabled"):
        port_hint = f"    -> http://{panel.get('host', '127.0.0.1')}:{panel.get('port', 8777)}/"
    if engine_env.has_venv(workspace):
        eng = engine_env.engine_command()
        lines += ["Engine commands, from the workspace folder (the skills use the same command):",
                  f"  {eng} status"]
        if panel.get("enabled"):
            lines.append(f"  {eng} panel{port_hint}")
        return "\n".join(lines)
    ws, repo = f'"{workspace}"', f'"{REPO_ROOT}"'
    lines += ["No workspace venv: engine commands run from the package folder:",
              f"  cd {repo}",
              f"  python -m agentos status --workspace {ws}"]
    if panel.get("enabled"):
        lines.append(f"  python -m agentos panel --workspace {ws}{port_hint}")
    lines += [
        "or from anywhere with the package folder on PYTHONPATH:",
        f"  macOS/Linux:  export PYTHONPATH={repo}",
        f"  Windows:      $env:PYTHONPATH = {repo}     (cmd.exe: set PYTHONPATH={REPO_ROOT})",
        "Re-run install.py without --no-venv to get the workspace venv.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- uninstall
def uninstall(workspace: Path, *, print_only: bool = False, out=print) -> list:
    workspace = Path(workspace).expanduser().resolve()
    if not (workspace / "agentos.toml").exists() and not (workspace / ".agentos").exists():
        raise InstallError(f"{workspace} does not look like a {PRODUCT_NAME} workspace")
    actions = []
    try:
        from agentos import scheduler

        actions += scheduler.remove(workspace, print_only=print_only, out=out)
    except Exception as exc:  # noqa: BLE001
        out(f"schedule removal failed: {exc}")
        actions.append(f"schedule removal failed: {exc}")
    runtime = workspace / ".agentos"
    for name in RUNTIME_REMOVABLE:
        p = runtime / name
        if p.is_file():
            actions.append(f"remove {p}")
            if print_only:
                out(f"[print-only] remove {p}")
            else:
                p.unlink()  # engine-owned runtime file, see RUNTIME_REMOVABLE
                out(f"removed {p}")
    vdir = runtime / "venv"
    if (vdir / "pyvenv.cfg").is_file():  # only a real venv created by install.py
        actions.append(f"remove {vdir}")
        if print_only:
            out(f"[print-only] remove {vdir} (engine virtual environment)")
        else:
            shutil.rmtree(vdir)  # engine-owned, recreated by install.py; no user data inside
            out(f"removed {vdir}")
    out("kept: agentos.toml, CLAUDE.md, .claude/, projects/, inbox/, ideas/, notes/, TODO.md, .agentos/logs/ "
        "(your data - delete by hand if you really want to)")
    return actions


# --------------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=f"{PRODUCT_NAME} installer")
    ap.add_argument("command", nargs="?", choices=["install", "uninstall"], default="install")
    ap.add_argument("--workspace", type=Path)
    ap.add_argument("--non-interactive", action="store_true")
    ap.add_argument("--owner")
    ap.add_argument("--language")
    ap.add_argument("--timezone")
    ap.add_argument("--profile", choices=PROFILES)
    ap.add_argument("--queue", dest="queue", action="store_true", default=None)
    ap.add_argument("--no-queue", dest="queue", action="store_false")
    ap.add_argument("--interval", type=int)
    ap.add_argument("--panel", dest="panel", action="store_true", default=None)
    ap.add_argument("--no-panel", dest="panel", action="store_false")
    ap.add_argument("--notify", choices=NOTIFY_KINDS)
    ap.add_argument("--with-demo", action="store_true")
    ap.add_argument("--rules", default="", help="optional rule packs to enable, comma separated (e.g. web,sales)")
    ap.add_argument("--no-schedule", action="store_true", help="never touch the OS scheduler")
    ap.add_argument("--schedule-print-only", action="store_true", help="print scheduler commands instead of running them")
    ap.add_argument("--print-only", action="store_true", help="uninstall: show what would be removed")
    ap.add_argument("--confirm-full", default="", help=f'required with --profile full: "{FULL_CONFIRMATION}"')
    ap.add_argument("--no-doctor", action="store_true")
    ap.add_argument("--no-venv", action="store_true",
                    help="do not create .agentos/venv; run the engine from the repo folder (PYTHONPATH)")
    return ap


def main(argv=None, input_fn=input, out=print) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "uninstall":
            if not args.workspace:
                raise InstallError("uninstall needs --workspace PATH")
            uninstall(args.workspace, print_only=args.print_only, out=out)
            return 0
        if args.non_interactive:
            if not args.workspace:
                raise InstallError("--non-interactive needs --workspace PATH")
            ws = args.workspace.expanduser()
            ans = resolve_answers(args, defaults_from_existing(ws))
            ans["workspace"] = ws
            ans["with_demo"] = args.with_demo
            ans["rules"] = args.rules
            ans["full_confirmed"] = args.confirm_full.strip() == FULL_CONFIRMATION or (
                ans["profile"] == "full" and defaults_from_existing(ws).get("profile") == "full"
            )
        else:
            ans = wizard(args, input_fn=input_fn)
        install(ans, schedule=not args.no_schedule, schedule_print_only=args.schedule_print_only,
                run_doctor=not args.no_doctor, out=out, create_venv=not args.no_venv)
        return 0
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("\naborted - nothing else was changed", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
