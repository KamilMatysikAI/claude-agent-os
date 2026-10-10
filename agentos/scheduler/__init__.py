"""Scheduler layer: run the agent queue periodically without a terminal window.

One public API, three backends:

* Windows  - Task Scheduler via ``schtasks`` running ``pythonw.exe`` (no console window).
* macOS    - a launchd agent (``StartInterval``) loaded with ``launchctl bootstrap gui/<uid>``.
* Linux    - a ``crontab`` line tagged with a ``# claude-agent-os:<id>`` marker
             (all other crontab lines are preserved), or optionally a ``systemd --user`` timer.

Every operation is first built as a *plan* (a list of actions) and only then executed.
``print_only=True`` prints the plan and touches nothing - this is how the tests and the
``--print-only`` flag work. The scheduled job runs a small launcher script
(``<workspace>/.agentos/tick.py``) that calls ``python -m agentos guard``, ``run``,
``dashboard`` and ``notify-digest`` for that workspace.

Safety: this module only ever creates, queries or removes jobs whose name starts with the
product prefix. It never lists or modifies any other scheduled job on the machine.
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Union

try:  # the engine owns agentos/__init__.py; keep working if it is not there yet
    from agentos import PRODUCT_NAME  # type: ignore
except Exception:  # pragma: no cover - fallback only
    PRODUCT_NAME = "claude-agent-os"
from agentos import env as engine_env  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = ".agentos"
LAUNCHER_NAME = "tick.py"
STATE_NAME = "schedule.json"

# Indirection so tests can mock every external command in one place.
RUNNER: Callable[..., subprocess.CompletedProcess] = subprocess.run


class SchedulerError(RuntimeError):
    """Raised when a scheduler command fails or the request is invalid."""


# --------------------------------------------------------------------------- actions
@dataclass
class WriteFile:
    path: Path
    content: Union[str, bytes]
    mode: Optional[int] = None

    def describe(self) -> str:
        size = len(self.content.encode("utf-8") if isinstance(self.content, str) else self.content)
        return f"write {self.path} ({size} bytes)"


@dataclass
class RemoveFile:
    path: Path

    def describe(self) -> str:
        return f"remove {self.path}"


@dataclass
class Run:
    argv: list
    input: Optional[str] = None
    ignore_errors: bool = False

    def describe(self) -> str:
        shown = subprocess.list2cmdline(self.argv) if os.name == "nt" else " ".join(_shquote(a) for a in self.argv)
        if self.input is not None:
            shown += "  <<stdin>>\n" + "\n".join("    " + line for line in self.input.splitlines())
        return f"run   {shown}"


Action = Union[WriteFile, RemoveFile, Run]


@dataclass
class ScheduleSpec:
    workspace: Path
    interval_minutes: int
    python: str
    launcher: Path
    job_id: str
    extra: dict = field(default_factory=dict)


def _shquote(s: str) -> str:
    import shlex

    return shlex.quote(str(s))


def run_cmd(argv: list, input: Optional[str] = None, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run an external command through the mockable RUNNER. Never raises on non-zero exit."""
    kwargs = dict(input=input, capture_output=True, text=True, errors="replace", timeout=timeout)
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return RUNNER(argv, **kwargs)
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(argv, 127, "", f"command not found: {exc}")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", "timeout")


def execute(plan: list, print_only: bool = False, out: Callable[[str], None] = print) -> list:
    """Execute (or just print) a plan. Returns the list of action descriptions."""
    done = []
    for action in plan:
        desc = action.describe()
        done.append(desc)
        if print_only:
            out("[print-only] " + desc)
            continue
        if isinstance(action, WriteFile):
            action.path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(action.content, bytes):
                action.path.write_bytes(action.content)
            else:
                action.path.write_text(action.content, encoding="utf-8", newline="\n")
            if action.mode is not None and os.name != "nt":
                os.chmod(action.path, action.mode)
        elif isinstance(action, RemoveFile):
            if action.path.exists():
                action.path.unlink()  # only our own unit/plist/launcher files reach here
        elif isinstance(action, Run):
            res = run_cmd(action.argv, input=action.input)
            if res.returncode != 0 and not action.ignore_errors:
                msg = (res.stderr or res.stdout or "").strip()
                raise SchedulerError(f"command failed ({res.returncode}): {action.describe()}\n{msg}")
        out(desc)
    return done


# --------------------------------------------------------------------------- naming
def detect_os(platform_name: Optional[str] = None) -> str:
    p = (platform_name or sys.platform).lower()
    if p.startswith("win"):
        return "windows"
    if p == "darwin" or p.startswith("mac"):
        return "macos"
    return "linux"


def job_id(workspace: Path) -> str:
    """Deterministic, filesystem/cron/launchd safe id for one workspace."""
    resolved = str(Path(workspace).resolve())
    key = resolved.lower() if os.name == "nt" else resolved
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    slug = re.sub(r"[^a-z0-9]+", "-", Path(resolved).name.lower()).strip("-")[:30] or "workspace"
    return f"{slug}-{digest}"


def assert_own_name(name: str) -> None:
    """Hard guard: never operate on a job that is not ours."""
    if not (name.startswith(PRODUCT_NAME) or name.startswith("com." + PRODUCT_NAME)):
        raise SchedulerError(f"refusing to touch foreign scheduled job: {name!r}")


def validate_interval(minutes: int) -> int:
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        raise SchedulerError(f"interval must be an integer number of minutes, got {minutes!r}")
    if minutes < 1 or minutes > 1439:
        raise SchedulerError("interval must be between 1 and 1439 minutes")
    return minutes


def default_python(os_name: str) -> str:
    """Interpreter for the scheduled job. On Windows prefer pythonw.exe (no console window)."""
    exe = Path(sys.executable)
    if os_name == "windows":
        candidate = exe.with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return str(exe)


def venv_or_default_python(workspace: Path, os_name: str) -> str:
    """The workspace venv (created by install.py) runs the job; sys.executable otherwise."""
    venv = engine_env.venv_python(workspace, windowed=True, os_name=os_name)
    if venv.is_file():
        return str(venv)
    plain = engine_env.venv_python(workspace, os_name=os_name)
    return str(plain) if plain.is_file() else default_python(os_name)


# --------------------------------------------------------------------------- launcher
LAUNCHER_TEMPLATE = '''\
# Generated by the {product} installer - engine-owned runtime file.
# Runs guard, the agent queue once, the dashboard refresh and the digest for one workspace.
# Removed by `python install.py uninstall`. Safe to delete by hand.
import datetime
import os
import subprocess
import sys

REPO = {repo!r}          # only used when the workspace has no venv (fallback)
USE_PYTHONPATH = {use_pythonpath!r}
WORKSPACE = {workspace!r}
EXTRA_PATH = {extra_path!r}
STEP_TIMEOUT = {timeout!r}
LOG = os.path.join(WORKSPACE, ".agentos", "logs", "scheduler.log")


def _log(line):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(datetime.datetime.now().isoformat(timespec="seconds") + " " + line + "\\n")
    except OSError:
        pass


def main():
    env = os.environ.copy()
    if USE_PYTHONPATH:
        env["PYTHONPATH"] = REPO + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    else:
        env.pop("PYTHONPATH", None)  # the venv has the installed package; nothing may shadow it
    if EXTRA_PATH:
        env["PATH"] = os.pathsep.join(EXTRA_PATH + [env.get("PATH", "")])
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # Each step is isolated: a failing queue run must not stop the dashboard refresh.
    for step in (["guard"], ["run"], ["dashboard"], ["notify-digest"]):
        try:
            os.makedirs(os.path.dirname(LOG), exist_ok=True)
            with open(LOG, "a", encoding="utf-8") as fh:
                rc = subprocess.call(
                    # -P: do not put the cwd (the agent-writable workspace) on sys.path,
                    # so a planted <workspace>/agentos/ can never shadow the real package.
                    [sys.executable, "-P", "-m", "agentos"] + step + ["--workspace", WORKSPACE],
                    cwd=WORKSPACE, env=env, stdout=fh, stderr=fh,
                    stdin=subprocess.DEVNULL, creationflags=flags, timeout=STEP_TIMEOUT,
                )
            _log("step %s exit=%s" % (step[0], rc))
        except Exception as exc:  # noqa: BLE001 - must never crash silently
            _log("step %s error: %r" % (step[0], exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _read_config(workspace: Path) -> dict:
    cfg_path = Path(workspace) / "agentos.toml"
    if not cfg_path.exists():
        return {}
    try:
        import tomllib

        return tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def launcher_source(workspace: Path, *, claude_bin: Optional[str] = None, timeout_minutes: int = 45) -> str:
    cfg = _read_config(workspace)
    queue = cfg.get("queue", {}) if isinstance(cfg.get("queue"), dict) else {}
    claude = claude_bin or queue.get("claude_bin") or "claude"
    found = shutil.which(claude)
    # Schedulers start with a minimal PATH; remember where the CLI lives at install time.
    extra = [str(Path(found).parent)] if found else []
    tmo = int(queue.get("timeout_minutes", timeout_minutes) or timeout_minutes)
    return LAUNCHER_TEMPLATE.format(
        product=PRODUCT_NAME,
        repo=str(REPO_ROOT),
        use_pythonpath=not engine_env.has_venv(workspace),
        workspace=str(Path(workspace).resolve()),
        extra_path=extra,
        timeout=(tmo + 15) * 60,
    )


def make_spec(workspace: Path, interval_minutes: int, os_name: str, python: Optional[str] = None) -> ScheduleSpec:
    ws = Path(workspace).resolve()
    return ScheduleSpec(
        workspace=ws,
        interval_minutes=validate_interval(interval_minutes),
        python=python or venv_or_default_python(ws, os_name),
        launcher=ws / RUNTIME_DIR / LAUNCHER_NAME,
        job_id=job_id(ws),
    )


# --------------------------------------------------------------------------- public API
def get_backend(os_name: str, linux_mode: str = "cron"):
    if os_name == "windows":
        from . import windows as backend
    elif os_name == "macos":
        from . import macos as backend
    elif os_name == "linux":
        from . import linux as backend

        return backend.SystemdBackend() if linux_mode == "systemd" else backend.CronBackend()
    else:
        raise SchedulerError(f"unknown OS: {os_name}")
    return backend.Backend()


def _state_path(workspace: Path) -> Path:
    return Path(workspace).resolve() / RUNTIME_DIR / STATE_NAME


def read_state(workspace: Path) -> dict:
    p = _state_path(workspace)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


def install(
    workspace: Path,
    interval_minutes: int,
    *,
    python: Optional[str] = None,
    print_only: bool = False,
    os_name: Optional[str] = None,
    linux_mode: str = "cron",
    out: Callable[[str], None] = print,
) -> list:
    """Install (or update in place) the periodic job for ``workspace``. Idempotent."""
    os_name = os_name or detect_os()
    spec = make_spec(workspace, interval_minutes, os_name, python)
    backend = get_backend(os_name, linux_mode)
    state = {
        "backend": backend.kind,
        "name": backend.name(spec.job_id),
        "interval_minutes": spec.interval_minutes,
        "python": spec.python,
        "launcher": str(spec.launcher),
        "repo": str(REPO_ROOT),
    }
    plan: list = [
        WriteFile(spec.launcher, launcher_source(spec.workspace)),
        WriteFile(_state_path(spec.workspace), json.dumps(state, indent=2, sort_keys=True) + "\n"),
    ]
    plan += backend.install_plan(spec)
    return execute(plan, print_only=print_only, out=out)


def remove(
    workspace: Path,
    *,
    print_only: bool = False,
    os_name: Optional[str] = None,
    linux_mode: Optional[str] = None,
    out: Callable[[str], None] = print,
) -> list:
    """Remove the job for ``workspace`` (no-op if absent). Never touches other jobs."""
    os_name = os_name or detect_os()
    state = read_state(workspace)
    mode = linux_mode or ("systemd" if state.get("backend") == "systemd" else "cron")
    backend = get_backend(os_name, mode)
    jid = job_id(Path(workspace))
    plan = backend.remove_plan(jid, Path(workspace).resolve())
    return execute(plan, print_only=print_only, out=out)


def status(workspace: Path, *, os_name: Optional[str] = None, linux_mode: Optional[str] = None) -> dict:
    os_name = os_name or detect_os()
    state = read_state(workspace)
    mode = linux_mode or ("systemd" if state.get("backend") == "systemd" else "cron")
    backend = get_backend(os_name, mode)
    jid = job_id(Path(workspace))
    result = backend.status(jid, Path(workspace).resolve())
    result.setdefault("name", backend.name(jid))
    result.setdefault("backend", backend.kind)
    result["state"] = state
    return result


# --------------------------------------------------------------------------- CLI
def find_workspace(start: Optional[Path] = None) -> Optional[Path]:
    cur = Path(start or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / "agentos.toml").exists():
            return p
    return None


def main(argv: Optional[list] = None) -> int:
    """``python -m agentos schedule install|remove|status``"""
    ap = argparse.ArgumentParser(prog="agentos schedule", description="Manage the periodic queue job.")
    ap.add_argument("action", choices=["install", "remove", "status"])
    ap.add_argument("--workspace", type=Path, default=None)
    ap.add_argument("--interval", type=int, default=None, help="minutes (default: from agentos.toml)")
    ap.add_argument("--print-only", action="store_true", help="show what would be done, change nothing")
    ap.add_argument("--systemd", action="store_true", help="Linux: use a systemd --user timer instead of cron")
    args = ap.parse_args(argv)

    ws = args.workspace or find_workspace()
    if ws is None or not (Path(ws) / "agentos.toml").exists():
        print("No workspace found (agentos.toml). Use --workspace PATH.", file=sys.stderr)
        return 2
    ws = Path(ws).resolve()
    try:
        if args.action == "install":
            cfg = _read_config(ws)
            interval = args.interval or cfg.get("queue", {}).get("interval_minutes", 30)
            install(ws, interval, print_only=args.print_only, linux_mode="systemd" if args.systemd else "cron")
        elif args.action == "remove":
            remove(ws, print_only=args.print_only, linux_mode="systemd" if args.systemd else None)
        else:
            st = status(ws)
            state = "installed" if st.get("installed") else "not installed"
            print(f"{st['backend']}: {st['name']} - {state}")
            if st.get("detail"):
                print(st["detail"])
    except SchedulerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
