"""Single CLI entry point: `python -m agentos <command> [--workspace PATH]`."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from . import PRODUCT_NAME, __version__, core
from .config import WorkspaceNotFound

DELEGATED = {
    # command: (module, hint when the module is not installed)
    "doctor": ("agentos.doctor", "the doctor module ships with the installer"),
    "schedule": ("agentos.scheduler", "the scheduler ships with the installer"),
    "panel": ("panel", "the panel is optional; install it to use this command"),
}


def _package_root() -> Path:
    """The folder that holds `agentos/`, `panel/` and `profiles/` (the cloned repo)."""
    return Path(__file__).resolve().parent.parent


def _delegate(command: str, rest: list[str]) -> int:
    module_name, hint = DELEGATED[command]
    root = str(_package_root())
    if module_name == "panel" and root not in sys.path:
        # `panel/` sits next to `agentos/`, not inside it. Whatever made `agentos`
        # importable (cwd = repo, PYTHONPATH, the scheduler's tick.py with -P) must make
        # the panel importable too, so append (never prepend) the repo root explicitly.
        sys.path.append(root)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        print(f"'{command}' is not available ({hint}): {exc}", file=sys.stderr)
        return 2
    entry = getattr(module, "main", None)
    if entry is None:
        print(f"'{command}' is not available: {module_name} has no main()", file=sys.stderr)
        return 2
    return int(entry(rest) or 0)


def _workspace(arg) -> Path:
    return Path(arg).resolve() if arg else core.find_workspace()


def cmd_status(ws: Path, cfg: dict, slug: str | None) -> int:
    snap = core.load_snapshot(ws)
    slugs = [slug] if slug else sorted(set(snap.projects) | {t.project for t in snap.tasks if t.project})
    wip = core.wip_counts(snap.tasks)
    for s in slugs:
        own = [t for t in snap.tasks if t.project == s]
        if slug and s not in snap.projects and not own:
            print(f"unknown project: {s}", file=sys.stderr)
            return 1
        counts = ", ".join(f"{st} {sum(1 for t in own if t.status == st)}" for st in core.STATUSES)
        limit = snap.wip_limit(s, cfg["projects"]["wip_limit"])
        print(f"{s} [{snap.project_status(s)}] WIP {wip.get(s, 0)}/{limit} - {counts}")
        if slug:
            for t in sorted(own, key=lambda t: t.id):
                if t.status in core.OPEN_STATUSES:
                    print(f"  {t.id:6} {t.status:11} {t.owner:9} {t.title}")
    inbox = [t for t in snap.tasks if not t.project and t.status in core.OPEN_STATUSES]
    if not slug:
        print(f"inbox: {len(inbox)} open")
    for err in snap.errors:
        print(f"unreadable: {err}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workspace", help="workspace path (default: search up for agentos.toml)")
    parser = argparse.ArgumentParser(prog="python -m agentos",
                                     description=f"{PRODUCT_NAME} {__version__}")
    parser.add_argument("--version", action="version", version=f"{PRODUCT_NAME} {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("dashboard", parents=[common], help="regenerate projects/dashboard.md and TODO.md block")
    g = sub.add_parser("guard", parents=[common], help="apply guard rules (idempotent)")
    g.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("status", parents=[common], help="project summary")
    s.add_argument("slug", nargs="?")
    r = sub.add_parser("run", parents=[common], help="run the queue once")
    r.add_argument("--task", help="run this task file (relative to the workspace)")
    r.add_argument("--dry-run", action="store_true", help="print the command, change nothing")
    n = sub.add_parser("notify-digest", parents=[common], help="send batched notifications if due")
    n.add_argument("--force", action="store_true", help="send now even outside a digest slot")
    i = sub.add_parser("next-id", parents=[common],
                       help="print the next free ID (counter shared by A- and H-)")
    i.add_argument("slug", help="project slug or 'inbox'")
    i.add_argument("prefix", choices=["A", "H"])
    for name in DELEGATED:
        sub.add_parser(name, help=f"{name} (delegated)", add_help=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in DELEGATED:
        return _delegate(argv[0], argv[1:])
    args = build_parser().parse_args(argv)
    try:
        ws = _workspace(args.workspace)
    except WorkspaceNotFound as exc:
        print(str(exc), file=sys.stderr)
        return 2
    cfg = core.load_config(ws)
    if cfg.get("_error"):
        core.log(ws, "cli", f"config: {cfg['_error']}")
        print(f"warning: {cfg['_error']} (using defaults)", file=sys.stderr)

    if args.command == "dashboard":
        from . import dashboard
        res = dashboard.generate(ws, cfg)
        print(f"dashboard: {res['tasks']} tasks, changed={res['dashboard_changed']}, "
              f"TODO changed={res['todo_changed']}")
        return 0
    if args.command == "guard":
        from . import guard
        res = guard.run_guard(ws, cfg, dry_run=args.dry_run)
        for line in res["actions"]:
            print(("[dry-run] " if args.dry_run else "") + line)
        for line in res["warnings"]:
            print(f"warning: {line}")
        for line in res["errors"]:
            print(f"error: {line}", file=sys.stderr)
        return 1 if res["errors"] else 0
    if args.command == "status":
        return cmd_status(ws, cfg, args.slug)
    if args.command == "run":
        from . import runner
        res = runner.run(ws, task_path=args.task, dry_run=args.dry_run, cfg=cfg)
        if not args.dry_run and (res.get("ran") or args.task):
            print(json.dumps(res, indent=2, default=str))
        return 0
    if args.command == "next-id":
        folder = ws / "inbox" if args.slug == "inbox" else core.projects_dir(ws) / args.slug
        if not folder.is_dir():
            print(f"error: not found: {folder}", file=sys.stderr)
            return 2
        print(core.next_id(folder, args.prefix))
        return 0
    if args.command == "notify-digest":
        from . import notify
        res = notify.digest(ws, cfg, force=args.force)
        if res.get("sent") or args.force:
            print(res.get("reason", ""))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
